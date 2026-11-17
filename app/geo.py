"""Subprefeitura mais próxima (centroides aproximados do seed do pipeline de dados) — só para a cidade de São Paulo."""
import csv
import math
from functools import lru_cache
from pathlib import Path

SEEDS = Path(__file__).resolve().parent.parent / "seeds"
SP_BBOX = (-24.1, -23.3, -46.85, -46.35)  # lat_min, lat_max, lon_min, lon_max


@lru_cache
def _subs():
    with open(SEEDS / "subprefeituras.csv", encoding="utf-8") as f:
        return [(r["nome"], float(r["centroide_lat_aprox"]), float(r["centroide_lon_aprox"])) for r in csv.DictReader(f)]


def dentro_sp(lat, lon) -> bool:
    return lat is not None and lon is not None and SP_BBOX[0] <= lat <= SP_BBOX[1] and SP_BBOX[2] <= lon <= SP_BBOX[3]


def subprefeitura(lat, lon):
    if not dentro_sp(lat, lon):
        return None
    def dist(s):
        dy = (s[1] - lat) * 111.0
        dx = (s[2] - lon) * 111.0 * math.cos(math.radians(lat))
        return dx * dx + dy * dy
    return min(_subs(), key=dist)[0]
