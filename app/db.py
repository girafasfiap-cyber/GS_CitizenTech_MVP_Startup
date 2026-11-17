"""Banco do app (SQLite). Um arquivo, sem servidor: suficiente para o MVP; trocar por Postgres exige só esta camada."""
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.getenv("DATA_DIR", "data"))
DB_PATH = DATA_DIR / "cidadeviva.sqlite"
FOTOS = DATA_DIR / "fotos"

SCHEMA = """
CREATE TABLE IF NOT EXISTS reporte (
  id TEXT PRIMARY KEY,
  codigo TEXT UNIQUE NOT NULL,
  created_at TEXT NOT NULL,
  canal TEXT NOT NULL DEFAULT 'web',
  descricao TEXT NOT NULL,
  texto_formal TEXT,
  foto_arquivo TEXT,
  logradouro TEXT, numero TEXT, bairro TEXT, cidade TEXT, uf TEXT, cep TEXT,
  endereco_origem TEXT,
  subprefeitura TEXT,
  lat REAL, lon REAL,
  ia_categoria TEXT, ia_confianca REAL, ia_modelo TEXT,
  categoria TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'novo',
  requer_revisao INTEGER NOT NULL DEFAULT 0,
  protocolo TEXT,
  erro_envio TEXT,
  usuario_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_reporte_status ON reporte(status);
CREATE INDEX IF NOT EXISTS ix_reporte_created ON reporte(created_at);
"""


def agora() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def init():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    FOTOS.mkdir(parents=True, exist_ok=True)
    with conn() as c:
        c.executescript(SCHEMA)


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    try:
        yield c
        c.commit()
    finally:
        c.close()


def novo_codigo(c) -> str:
    alfabeto = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # sem 0/O/1/I: o cidadão digita sem errar
    while True:
        cod = "CV-" + "".join(secrets.choice(alfabeto) for _ in range(6))
        if not c.execute("SELECT 1 FROM reporte WHERE codigo=?", (cod,)).fetchone():
            return cod


def inserir(dados: dict) -> dict:
    with conn() as c:
        dados = {**dados, "id": uuid.uuid4().hex, "codigo": novo_codigo(c), "created_at": agora()}
        cols = ", ".join(dados)
        c.execute(f"INSERT INTO reporte ({cols}) VALUES ({', '.join('?' * len(dados))})", list(dados.values()))
    return dados
