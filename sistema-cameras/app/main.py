"""Servidor web: API + página do app.

Rodar:  uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import csv
import hashlib
import hmac
import io
import os
import shutil
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .camera import Camera
from .db import Banco

RAIZ = Path(__file__).resolve().parent.parent
CONFIG = yaml.safe_load(open(os.environ.get("CONFIG", RAIZ / "config.yaml"), encoding="utf-8"))
DADOS = Path(CONFIG.get("pasta_dados", "dados"))
if not DADOS.is_absolute():
    DADOS = RAIZ / DADOS
CONFIG["pasta_dados"] = str(DADOS)

banco = Banco(DADOS / "eventos.db")
cameras: dict[str, Camera] = {}
for c in CONFIG["cameras"]:
    cam = Camera(c, CONFIG, banco)
    cameras[cam.id] = cam

TOKEN = hmac.new(str(CONFIG["senha"]).encode(), b"sistema-cameras", hashlib.sha256).hexdigest()


# ------------------------------------------------------------ limpeza antiga
def limpar_antigos():
    """Apaga vídeos e fotos com mais de `dias_guardar` dias. Os dados ficam."""
    dias = float(CONFIG.get("dias_guardar", 7))
    while True:
        limite = time.time() - dias * 86400
        for pasta in ("gravacoes", "eventos"):
            for arq in (DADOS / pasta).glob("*/*"):
                if arq.is_file() and arq.stat().st_mtime < limite:
                    arq.unlink(missing_ok=True)
        time.sleep(1800)


@asynccontextmanager
async def ciclo(_app):
    for cam in cameras.values():
        cam.iniciar()
    threading.Thread(target=limpar_antigos, daemon=True).start()
    yield
    for cam in cameras.values():
        cam.parar()


app = FastAPI(title="Sistema de Câmeras", lifespan=ciclo)


# ------------------------------------------------------------------- login
def logado(request: Request):
    if not hmac.compare_digest(request.cookies.get("token", ""), TOKEN):
        raise HTTPException(401, "Faça login")


@app.post("/api/login")
async def login(request: Request, response: Response):
    dados = await request.json()
    if not hmac.compare_digest(str(dados.get("senha", "")), str(CONFIG["senha"])):
        await asyncio.sleep(1)  # dificulta adivinhar a senha
        raise HTTPException(401, "Senha incorreta")
    response.set_cookie("token", TOKEN, max_age=60 * 60 * 24 * 90, httponly=True, samesite="lax")
    return {"ok": True}


@app.post("/api/sair")
def sair(response: Response):
    response.delete_cookie("token")
    return {"ok": True}


def pegar_camera(cam_id: str) -> Camera:
    if cam_id not in cameras:
        raise HTTPException(404, "Câmera não encontrada")
    return cameras[cam_id]


# ----------------------------------------------------------------- câmeras
@app.get("/api/cameras", dependencies=[Depends(logado)])
def listar_cameras():
    uso = shutil.disk_usage(DADOS)
    return {
        "cameras": [c.status() for c in cameras.values()],
        "disco": {"livre_gb": round(uso.free / 1e9, 1), "total_gb": round(uso.total / 1e9, 1)},
    }


@app.get("/api/cameras/{cam_id}/foto", dependencies=[Depends(logado)])
def foto_atual(cam_id: str):
    img = pegar_camera(cam_id).imagem()
    if not img:
        raise HTTPException(503, "Câmera sem imagem")
    return Response(img, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@app.get("/api/cameras/{cam_id}/ao-vivo", dependencies=[Depends(logado)])
async def ao_vivo(cam_id: str, request: Request):
    cam = pegar_camera(cam_id)

    async def gerar():
        ultima = None
        while not await request.is_disconnected():
            img = cam.imagem()
            if img and img is not ultima:
                ultima = img
                yield b"--quadro\r\nContent-Type: image/jpeg\r\n\r\n" + img + b"\r\n"
            await asyncio.sleep(0.1)

    return StreamingResponse(gerar(), media_type="multipart/x-mixed-replace; boundary=quadro")


# ----------------------------------------------------------------- eventos
def filtro_eventos(camera: str | None, dia: str | None):
    where, params = ["1=1"], []
    if camera:
        where.append("camera = ?")
        params.append(camera)
    if dia:
        ini = datetime.strptime(dia, "%Y-%m-%d").timestamp()
        where.append("inicio >= ? AND inicio < ?")
        params += [ini, ini + 86400]
    return " AND ".join(where), params


@app.get("/api/eventos", dependencies=[Depends(logado)])
def listar_eventos(camera: str | None = None, dia: str | None = None, limite: int = 100):
    where, params = filtro_eventos(camera, dia)
    linhas = banco.consultar(
        f"SELECT * FROM eventos WHERE {where} ORDER BY inicio DESC LIMIT ?", params + [min(limite, 1000)]
    )
    for e in linhas:
        e["tem_foto"] = bool(e["foto"]) and (DADOS / "eventos" / e["foto"]).exists()
        e["duracao"] = round((e["fim"] or time.time()) - e["inicio"], 1)
    return linhas


@app.get("/api/eventos/{evento_id}/foto", dependencies=[Depends(logado)])
def foto_evento(evento_id: int):
    linhas = banco.consultar("SELECT foto FROM eventos WHERE id = ?", (evento_id,))
    if not linhas or not linhas[0]["foto"]:
        raise HTTPException(404)
    caminho = DADOS / "eventos" / linhas[0]["foto"]
    if not caminho.exists():
        raise HTTPException(404, "Foto já apagada")
    return FileResponse(caminho, media_type="image/jpeg")


@app.get("/api/eventos.csv", dependencies=[Depends(logado)])
def exportar_csv(camera: str | None = None, dia: str | None = None):
    """Exporta tudo para analisar no pandas / Excel / Power BI."""
    where, params = filtro_eventos(camera, dia)
    linhas = banco.consultar(f"SELECT * FROM eventos WHERE {where} ORDER BY inicio", params)
    saida = io.StringIO()
    w = csv.writer(saida)
    w.writerow(["id", "camera", "inicio", "fim", "duracao_seg", "pico_area_pct"])
    for e in linhas:
        fim = e["fim"] or e["inicio"]
        w.writerow([
            e["id"], e["camera"],
            datetime.fromtimestamp(e["inicio"]).isoformat(sep=" ", timespec="seconds"),
            datetime.fromtimestamp(fim).isoformat(sep=" ", timespec="seconds"),
            round(fim - e["inicio"], 1), e["pico"],
        ])
    return Response(
        saida.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=eventos.csv"},
    )


# ---------------------------------------------------------------- gravações
def dia_passado(dia: str | None) -> bool:
    return bool(dia) and dia < datetime.now().strftime("%Y-%m-%d")


@app.get("/api/gravacoes", dependencies=[Depends(logado)])
def listar_gravacoes(camera: str, dia: str | None = None):
    cam = pegar_camera(camera)
    padrao = f"{dia}_*.mp4" if dia else "*.mp4"
    arquivos = sorted(cam.pasta_videos.glob(padrao), reverse=True)
    resultado = []
    for i, arq in enumerate(arquivos[:300]):
        try:
            inicio = datetime.strptime(arq.stem, "%Y-%m-%d_%H-%M-%S").timestamp()
        except ValueError:
            continue
        fim = arq.stat().st_mtime
        eventos = banco.consultar(
            "SELECT COUNT(*) AS n FROM eventos WHERE camera = ? AND inicio BETWEEN ? AND ?",
            (cam.id, inicio, fim),
        )[0]["n"]
        resultado.append({
            "arquivo": arq.name,
            "inicio": inicio,
            "tamanho_mb": round(arq.stat().st_size / 1e6, 1),
            "eventos": eventos,
            "gravando": i == 0 and cam.gravando and not dia_passado(dia),
        })
    return resultado


@app.get("/api/gravacoes/{camera}/{arquivo}", dependencies=[Depends(logado)])
def baixar_gravacao(camera: str, arquivo: str):
    cam = pegar_camera(camera)
    caminho = (cam.pasta_videos / arquivo).resolve()
    if caminho.parent != cam.pasta_videos.resolve() or not caminho.exists():
        raise HTTPException(404)
    return FileResponse(caminho, media_type="video/mp4")


# -------------------------------------------------------------- estatísticas
@app.get("/api/estatisticas", dependencies=[Depends(logado)])
def estatisticas(dias: int = 30):
    desde = (datetime.now() - timedelta(days=dias - 1)).replace(hour=0, minute=0, second=0).timestamp()
    eventos = banco.consultar(
        "SELECT camera, inicio, COALESCE(fim, inicio) AS fim FROM eventos WHERE inicio >= ?", (desde,)
    )
    nomes = {c.id: c.nome for c in cameras.values()}
    lista_dias = [(datetime.fromtimestamp(desde) + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(dias)]
    por_dia = {cid: dict.fromkeys(lista_dias, 0) for cid in nomes}
    por_hora = {cid: [0] * 24 for cid in nomes}
    semana = [0] * 7
    duracao_total = 0.0
    for e in eventos:
        d = datetime.fromtimestamp(e["inicio"])
        cid = e["camera"]
        if cid not in nomes:
            continue
        por_dia[cid][d.strftime("%Y-%m-%d")] = por_dia[cid].get(d.strftime("%Y-%m-%d"), 0) + 1
        por_hora[cid][d.hour] += 1
        semana[d.weekday()] += 1
        duracao_total += e["fim"] - e["inicio"]

    total_hora = [sum(por_hora[c][h] for c in nomes) for h in range(24)]
    hoje = datetime.now().strftime("%Y-%m-%d")
    return {
        "cameras": nomes,
        "dias": lista_dias,
        "por_dia": {c: list(v.values()) for c, v in por_dia.items()},
        "por_hora": por_hora,
        "dia_semana": semana,
        "resumo": {
            "total": len(eventos),
            "hoje": sum(por_dia[c].get(hoje, 0) for c in nomes),
            "media_dia": round(len(eventos) / dias, 1),
            "hora_pico": total_hora.index(max(total_hora)) if eventos else None,
            "minutos_movimento": round(duracao_total / 60, 1),
        },
    }


# ------------------------------------------------------------- página do app
app.mount("/", StaticFiles(directory=RAIZ / "static", html=True), name="static")
