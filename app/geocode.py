"""Preenchimento de endereço: CEP -> ViaCEP e coordenada -> OpenStreetMap (Nominatim). Tudo passa pelo servidor.

Falha com elegância: se o serviço externo cair, devolve None e a tela segue com digitação manual.
"""
import json
import logging
import re
import urllib.parse
import urllib.request
from functools import lru_cache

log = logging.getLogger("geocode")
UA = "CidadeViva-GS-FIAP/1.0 (projeto academico; zeladoria urbana)"  # a política do Nominatim exige identificar o aplicativo
TIMEOUT = 6


def _http_json(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def limpar_cep(cep: str) -> str | None:
    d = re.sub(r"\D", "", cep or "")
    return d if len(d) == 8 else None


@lru_cache(maxsize=2048)
def viacep(cep8: str) -> dict | None:
    try:
        j = _http_json(f"https://viacep.com.br/ws/{cep8}/json/")
    except Exception as e:
        log.warning("ViaCEP indisponível: %s", e)
        return None
    if not isinstance(j, dict) or j.get("erro"):
        return None
    return {"cep": f"{cep8[:5]}-{cep8[5:]}", "logradouro": (j.get("logradouro") or "").strip(), "bairro": (j.get("bairro") or "").strip(),
            "cidade": (j.get("localidade") or "").strip(), "uf": (j.get("uf") or "").strip().upper()}


_REVERSO: dict = {}


def reverso(lat: float, lon: float) -> dict | None:
    chave = (round(lat, 4), round(lon, 4))  # ~11 m: evita repetir a mesma consulta
    if chave in _REVERSO:
        return _REVERSO[chave]
    q = urllib.parse.urlencode({"format": "jsonv2", "lat": lat, "lon": lon, "zoom": 18, "addressdetails": 1, "accept-language": "pt-BR"})
    try:
        j = _http_json("https://nominatim.openstreetmap.org/reverse?" + q)
    except Exception as e:
        log.warning("Nominatim indisponível: %s", e)
        return None
    a = j.get("address") if isinstance(j, dict) else None
    if not a:
        return None
    iso = a.get("ISO3166-2-lvl4", "")
    res = {
        "logradouro": a.get("road") or a.get("pedestrian") or a.get("footway") or "",
        "numero": a.get("house_number") or "",
        "bairro": a.get("suburb") or a.get("neighbourhood") or a.get("quarter") or "",
        "cidade": a.get("city") or a.get("town") or a.get("municipality") or a.get("village") or "",
        "uf": iso.split("-")[-1] if iso.startswith("BR-") else "",
        "cep": a.get("postcode") or "",
    }
    if len(_REVERSO) > 2048:
        _REVERSO.clear()
    _REVERSO[chave] = res
    return res
