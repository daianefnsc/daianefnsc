"""Cada câmera tem duas tarefas rodando em paralelo:

1. Gravação: o ffmpeg copia o vídeo da câmera direto para arquivos .mp4
   (sem recodificar, então quase não usa processador).
2. Análise: o OpenCV lê o stream de baixa qualidade, detecta movimento,
   registra eventos no banco e gera a imagem "ao vivo".
"""
import os
import re
import subprocess
import threading
import time
import unicodedata
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

os.environ.setdefault("OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp")


def slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-") or "camera"


def eh_arquivo(fonte: str) -> bool:
    """Permite testar com um vídeo .mp4 no lugar da câmera."""
    return "://" not in fonte


class Camera:
    def __init__(self, cfg: dict, config: dict, banco):
        self.nome = cfg["nome"]
        self.id = slug(self.nome)
        self.principal = str(cfg["principal"])
        self.secundario = str(cfg.get("secundario") or cfg["principal"])
        self.gravar = cfg.get("gravar", True)

        mov = config.get("movimento", {})
        self.sensibilidade = int(mov.get("sensibilidade", 25))
        self.area_minima = float(mov.get("area_minima", 1.5))
        self.segundos_fim = float(mov.get("segundos_fim", 5))
        self.segmento = int(config.get("segmento_minutos", 10)) * 60

        dados = Path(config["pasta_dados"])
        self.pasta_videos = dados / "gravacoes" / self.id
        self.pasta_fotos = dados / "eventos" / self.id
        self.pasta_videos.mkdir(parents=True, exist_ok=True)
        self.pasta_fotos.mkdir(parents=True, exist_ok=True)

        self.banco = banco
        self.rodando = False
        self.online = False
        self.gravando = False
        self.em_movimento = False
        self.area_atual = 0.0
        self.jpeg: bytes | None = None
        self._lock = threading.Lock()
        self._evento_id = None
        self._evento_pico = 0.0
        self._ultimo_mov = 0.0
        self._ffmpeg: subprocess.Popen | None = None

    # ------------------------------------------------------------------ ciclo
    def iniciar(self):
        self.rodando = True
        threading.Thread(target=self._loop_analise, daemon=True).start()
        if self.gravar:
            threading.Thread(target=self._loop_gravacao, daemon=True).start()

    def parar(self):
        self.rodando = False
        if self._ffmpeg and self._ffmpeg.poll() is None:
            self._ffmpeg.terminate()
        self._fechar_evento()

    def status(self) -> dict:
        return {
            "id": self.id,
            "nome": self.nome,
            "online": self.online,
            "gravando": self.gravando,
            "em_movimento": self.em_movimento,
            "area": round(self.area_atual, 2),
        }

    def imagem(self) -> bytes | None:
        with self._lock:
            return self.jpeg

    # -------------------------------------------------------------- gravação
    def _loop_gravacao(self):
        while self.rodando:
            entrada = ["-rtsp_transport", "tcp", "-i", self.principal]
            if eh_arquivo(self.principal):
                entrada = ["-re", "-stream_loop", "-1", "-i", self.principal]
            cmd = [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin",
                *entrada,
                "-map", "0:v:0", "-map", "0:a:0?",
                "-c:v", "copy", "-c:a", "aac",
                "-f", "segment", "-segment_time", str(self.segmento),
                "-segment_atclocktime", "1", "-reset_timestamps", "1",
                "-segment_format_options", "movflags=+faststart",
                "-strftime", "1",
                str(self.pasta_videos / "%Y-%m-%d_%H-%M-%S.mp4"),
            ]
            try:
                self._ffmpeg = subprocess.Popen(cmd, stderr=subprocess.PIPE)
                self.gravando = True
                _, erro = self._ffmpeg.communicate()
                if self.rodando and erro:
                    print(f"[{self.nome}] gravação parou: {erro.decode(errors='ignore')[-300:]}")
            except FileNotFoundError:
                print("ffmpeg não encontrado! Instale o ffmpeg para gravar.")
                self.gravando = False
                return
            self.gravando = False
            if self.rodando:
                time.sleep(10)  # câmera caiu? tenta de novo

    # --------------------------------------------------------------- análise
    def _loop_analise(self):
        while self.rodando:
            fonte = self.secundario
            cap = cv2.VideoCapture(fonte, cv2.CAP_FFMPEG)
            if not cap.isOpened():
                self.online = False
                time.sleep(5)
                continue
            self.online = True
            fps_arquivo = cap.get(cv2.CAP_PROP_FPS) or 15
            fundo = None
            ultima_analise = 0.0
            ultimo_jpeg = 0.0
            inicio = time.time()

            while self.rodando:
                ok, frame = cap.read()
                if not ok:
                    break
                agora = time.time()
                if eh_arquivo(fonte):
                    time.sleep(1 / fps_arquivo)  # simula tempo real

                # Análise de movimento ~5x por segundo
                if agora - ultima_analise >= 0.2:
                    ultima_analise = agora
                    pequeno = cv2.resize(frame, (320, int(320 * frame.shape[0] / frame.shape[1])))
                    cinza = cv2.GaussianBlur(cv2.cvtColor(pequeno, cv2.COLOR_BGR2GRAY), (21, 21), 0)
                    if fundo is None:
                        fundo = cinza.astype("float")
                        continue
                    diff = cv2.absdiff(cinza, cv2.convertScaleAbs(fundo))
                    cv2.accumulateWeighted(cinza, fundo, 0.05)  # fundo se adapta à luz
                    _, mascara = cv2.threshold(diff, self.sensibilidade, 255, cv2.THRESH_BINARY)
                    mascara = cv2.dilate(mascara, None, iterations=2)
                    self.area_atual = 100.0 * np.count_nonzero(mascara) / mascara.size
                    if agora - inicio > 3:  # ignora os primeiros segundos
                        self._processar_movimento(self.area_atual, frame, agora)

                # Imagem ao vivo ~8x por segundo
                if agora - ultimo_jpeg >= 0.12:
                    ultimo_jpeg = agora
                    ao_vivo = frame
                    if frame.shape[1] > 960:
                        ao_vivo = cv2.resize(frame, (960, int(960 * frame.shape[0] / frame.shape[1])))
                    ok, buf = cv2.imencode(".jpg", ao_vivo, [cv2.IMWRITE_JPEG_QUALITY, 75])
                    if ok:
                        with self._lock:
                            self.jpeg = buf.tobytes()

            cap.release()
            self.online = eh_arquivo(fonte)  # vídeo de teste só reinicia
            if not eh_arquivo(fonte):
                time.sleep(3)

    def _processar_movimento(self, area: float, frame, agora: float):
        if area >= self.area_minima:
            self._ultimo_mov = agora
            if self._evento_id is None:
                nome_foto = datetime.fromtimestamp(agora).strftime("%Y-%m-%d_%H-%M-%S") + ".jpg"
                cv2.imwrite(str(self.pasta_fotos / nome_foto), frame, [cv2.IMWRITE_JPEG_QUALITY, 80])
                self._evento_id = self.banco.executar(
                    "INSERT INTO eventos (camera, inicio, pico, foto) VALUES (?, ?, ?, ?)",
                    (self.id, agora, area, f"{self.id}/{nome_foto}"),
                )
                self._evento_pico = area
                self.em_movimento = True
            self._evento_pico = max(self._evento_pico, area)
        elif self._evento_id is not None and agora - self._ultimo_mov > self.segundos_fim:
            self._fechar_evento()

    def _fechar_evento(self):
        if self._evento_id is not None:
            self.banco.executar(
                "UPDATE eventos SET fim = ?, pico = ? WHERE id = ?",
                (self._ultimo_mov, round(self._evento_pico, 2), self._evento_id),
            )
        self._evento_id = None
        self.em_movimento = False
