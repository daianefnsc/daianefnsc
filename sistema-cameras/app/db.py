"""Banco de dados SQLite com os eventos de movimento (a parte de dados!)."""
import sqlite3
import threading
from pathlib import Path


class Banco:
    def __init__(self, caminho: Path):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(caminho, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS eventos (
                    id      INTEGER PRIMARY KEY AUTOINCREMENT,
                    camera  TEXT NOT NULL,
                    inicio  REAL NOT NULL,   -- timestamp unix
                    fim     REAL,            -- NULL enquanto o movimento continua
                    pico    REAL DEFAULT 0,  -- maior % da imagem em movimento
                    foto    TEXT             -- caminho da foto do evento
                );
                CREATE INDEX IF NOT EXISTS idx_eventos_inicio ON eventos(inicio);
                """
            )
            # Eventos que ficaram abertos (sistema desligado no meio) são fechados.
            self.conn.execute("UPDATE eventos SET fim = inicio WHERE fim IS NULL")
            self.conn.commit()

    def executar(self, sql: str, params=()):
        with self.lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur.lastrowid

    def consultar(self, sql: str, params=()):
        with self.lock:
            return [dict(r) for r in self.conn.execute(sql, params).fetchall()]
