"""Gera um DW pequeno (só o que o /painel usa) a partir do cidadeviva_dw.sqlite completo do pipeline de Big Data.

Uso:  python tools/enxugar_dw.py CAMINHO/cidadeviva_dw.sqlite data_dw/cidadeviva_dw.sqlite
O arquivo completo tem centenas de milhares de linhas (fato_solicitacao_sp156); o painel só lê o mart agregado e as dimensões.
"""
import os
import sqlite3
import sys

TABELAS = ["dim_subprefeitura", "dim_categoria", "mart_demanda_subprefeitura_mes"]

if len(sys.argv) != 3:
    sys.exit(__doc__)
origem, destino = sys.argv[1], sys.argv[2]
os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
if os.path.exists(destino):
    os.remove(destino)
src, dst = sqlite3.connect(origem), sqlite3.connect(destino)
for t in TABELAS:
    ddl = src.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (t,)).fetchone()
    if not ddl:
        sys.exit(f"Tabela ausente na origem: {t}")
    dst.execute(ddl[0])
    cols = [r[1] for r in src.execute(f"PRAGMA table_info({t})")]
    rows = src.execute(f"SELECT {','.join(cols)} FROM {t}").fetchall()
    dst.executemany(f"INSERT INTO {t} VALUES ({','.join('?' * len(cols))})", rows)
    print(f"{t}: {len(rows)} linhas")
dst.commit()
dst.execute("VACUUM")
dst.close()
print(f"ok -> {destino} ({os.path.getsize(destino) / 1024:.0f} KB)")
