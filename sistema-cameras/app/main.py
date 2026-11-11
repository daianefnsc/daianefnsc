"""Servidor web: API + página do app.

Rodar:  python -m uvicorn app.main:app --host 0.0.0.0 --port 8000

Usa Starlette (Python puro, sem partes compiladas) para instalar fácil
até em tablet/celular Android.
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
from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

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
rotas: list[Route] = []


def rota(caminho: str, metodos=("GET",), publica=False):
    """Registra uma rota da API. Por padrão exige login."""
    def registrar(func):
        async def handler(request: Request):
            if not publica and not hmac.compare_digest(request.cookies.get("token", ""), TOKEN):
                return JSONResponse({"erro": "Faça login"}, status_code=401)
            try:
                resultado = func(request)
                if asyncio.iscoroutine(resultado):
                    resultado = await resultado
            except HTTPException as e:
                return JSONResponse({"erro": e.detail}, status_code=e.status_code)
            except ValueError:
                return JSONResponse({"erro": "Parâmetro inválido"}, status_code=400)
            return resultado if isinstance(resultado, Response) else JSONResponse(resultado)
        rotas.append(Route(caminho, handler, methods=list(metodos)))
        return func
    return registrar


def pegar_camera(cam_id: str | None) -> Camera:
    if cam_id not in cameras:
        raise HTTPException(404, "Câmera não encontrada")
    return cameras[cam_id]


# ------------------------------------------------------------ limpeza antiga
def limpar_antigos():
    """Apaga vídeos e fotos com mais de `dias_guardar` dias e, se o espaço livre
    ficar abaixo de `espaco_minimo_gb`, apaga os vídeos mais antigos até liberar.
    Os dados dos eventos (banco) nunca são apagados."""
    dias = float(CONFIG.get("dias_guardar", 7))
    minimo = float(CONFIG.get("espaco_minimo_gb", 5)) * 1e9
    while True:
        limite = time.time() - dias * 86400
        for pasta in ("gravacoes", "eventos"):
            for arq in (DADOS / pasta).glob("*/*"):
                if arq.is_file() and arq.stat().st_mtime < limite:
                    arq.unlink(missing_ok=True)
        if shutil.disk_usage(DADOS).free < minimo:
            # do mais antigo para o mais novo, sem mexer nos que estão gravando agora
            videos = sorted((DADOS / "gravacoes").glob("*/*.mp4"), key=lambda a: a.stat().st_mtime)
            for arq in videos:
                if shutil.disk_usage(DADOS).free >= minimo or time.time() - arq.stat().st_mtime < 120:
                    break
                print(f"Pouco espaço: apagando {arq.name}")
                arq.unlink(missing_ok=True)
        time.sleep(300)


# ------------------------------------------------------------------- login
@rota("/api/login", metodos=("POST",), publica=True)
async def login(request: Request):
    dados = await request.json()
    if not hmac.compare_digest(str(dados.get("senha", "")), str(CONFIG["senha"])):
        await asyncio.sleep(1)  # dificulta adivinhar a senha
        raise HTTPException(401, "Senha incorreta")
    resp = JSONResponse({"ok": True})
    resp.set_cookie("token", TOKEN, max_age=60 * 60 * 24 * 90, httponly=True, samesite="lax")
    return resp


@rota("/api/sair", metodos=("POST",), publica=True)
def sair(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie("token")
    return resp


# ----------------------------------------------------------------- câmeras
@rota("/api/cameras")
def listar_cameras(request: Request):
    uso = shutil.disk_usage(DADOS)
    return {
        "cameras": [c.status() for c in cameras.values()],
        "disco": {"livre_gb": round(uso.free / 1e9, 1), "total_gb": round(uso.total / 1e9, 1)},
    }


@rota("/api/cameras/{cam_id}/foto")
def foto_atual(request: Request):
    img = pegar_camera(request.path_params["cam_id"]).imagem()
    if not img:
        raise HTTPException(503, "Câmera sem imagem")
    return Response(img, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@rota("/api/cameras/{cam_id}/ao-vivo")
def ao_vivo(request: Request):
    cam = pegar_camera(request.path_params["cam_id"])

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
def filtro_eventos(request: Request):
    camera, dia = request.query_params.get("camera"), request.query_params.get("dia")
    where, params = ["1=1"], []
    if camera:
        where.append("camera = ?")
        params.append(camera)
    if dia:
        ini = datetime.strptime(dia, "%Y-%m-%d").timestamp()
        where.append("inicio >= ? AND inicio < ?")
        params += [ini, ini + 86400]
    return " AND ".join(where), params


@rota("/api/eventos")
def listar_eventos(request: Request):
    where, params = filtro_eventos(request)
    limite = min(int(request.query_params.get("limite", 100)), 1000)
    linhas = banco.consultar(f"SELECT * FROM eventos WHERE {where} ORDER BY inicio DESC LIMIT ?", params + [limite])
    for e in linhas:
        e["tem_foto"] = bool(e["foto"]) and (DADOS / "eventos" / e["foto"]).exists()
        e["duracao"] = round((e["fim"] or time.time()) - e["inicio"], 1)
    return linhas


@rota("/api/eventos/{evento_id:int}/foto")
def foto_evento(request: Request):
    linhas = banco.consultar("SELECT foto FROM eventos WHERE id = ?", (request.path_params["evento_id"],))
    if not linhas or not linhas[0]["foto"]:
        raise HTTPException(404, "Evento não encontrado")
    caminho = DADOS / "eventos" / linhas[0]["foto"]
    if not caminho.exists():
        raise HTTPException(404, "Foto já apagada")
    return FileResponse(caminho, media_type="image/jpeg")


@rota("/api/eventos.csv")
def exportar_csv(request: Request):
    """Exporta tudo para analisar no pandas / Excel / Power BI."""
    where, params = filtro_eventos(request)
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
@rota("/api/gravacoes")
def listar_gravacoes(request: Request):
    cam = pegar_camera(request.query_params.get("camera"))
    dia = request.query_params.get("dia")
    arquivos = sorted(cam.pasta_videos.glob(f"{dia}_*.mp4" if dia else "*.mp4"), reverse=True)
    ultimo = max(cam.pasta_videos.glob("*.mp4"), default=None)
    resultado = []
    for arq in arquivos[:300]:
        try:
            inicio = datetime.strptime(arq.stem, "%Y-%m-%d_%H-%M-%S").timestamp()
        except ValueError:
            continue
        fim = arq.stat().st_mtime
        eventos = banco.consultar(
            "SELECT COUNT(*) AS n FROM eventos WHERE camera = ? AND inicio < ? AND COALESCE(fim, ?) >= ?",
            (cam.id, fim, time.time(), inicio),
        )[0]["n"]
        resultado.append({
            "arquivo": arq.name,
            "inicio": inicio,
            "tamanho_mb": round(arq.stat().st_size / 1e6, 1),
            "eventos": eventos,
            "gravando": arq == ultimo and cam.gravando,
        })
    return resultado


@rota("/api/gravacoes/{camera}/{arquivo}")
def baixar_gravacao(request: Request):
    cam = pegar_camera(request.path_params["camera"])
    caminho = (cam.pasta_videos / request.path_params["arquivo"]).resolve()
    if caminho.parent != cam.pasta_videos.resolve() or not caminho.exists():
        raise HTTPException(404, "Gravação não encontrada")
    return FileResponse(caminho, media_type="video/mp4")


# -------------------------------------------------------------- estatísticas
@rota("/api/estatisticas")
def estatisticas(request: Request):
    dias = max(1, min(int(request.query_params.get("dias", 30)), 366))
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
        cid = e["camera"]
        if cid not in nomes:
            continue
        d = datetime.fromtimestamp(e["inicio"])
        chave = d.strftime("%Y-%m-%d")
        if chave in por_dia[cid]:
            por_dia[cid][chave] += 1
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


# ------------------------------------------------------------- app completo
@asynccontextmanager
async def ciclo(_app):
    for cam in cameras.values():
        cam.iniciar()
    threading.Thread(target=limpar_antigos, daemon=True).start()
    yield
    for cam in cameras.values():
        cam.parar()


app = Starlette(
    routes=[*rotas, Mount("/", StaticFiles(directory=RAIZ / "static", html=True), name="static")],
    lifespan=ciclo,
)
