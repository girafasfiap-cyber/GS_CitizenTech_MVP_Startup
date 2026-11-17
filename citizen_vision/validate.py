"""Etapa 6 — validação do endereço extraído."""
from __future__ import annotations

import json
import re
import urllib.request

from .config import UFS

REQUIRED = ("logradouro", "numero", "bairro", "cidade", "uf", "cep")


_CITY_RE = re.compile(r"^[A-Z][A-Z .'\-]*$")            # cidade: só letras (sem dígitos nem símbolos)
_BAIRRO_RE = re.compile(r"^[A-Z0-9][A-Z0-9 .'\-]*$")    # bairro: letras/dígitos, sem símbolos


def check_fields(addr: dict) -> tuple[list[str], list[str]]:
    """Retorna (avisos, campos_duvidosos). Campo duvidoso = ausente OU preenchido com algo implausível
    (ex.: texto de outra parte da fatura que o OCR capturou por engano)."""
    warnings, fields = [], []

    def flag(field: str, msg: str):
        warnings.append(msg)
        if field not in fields:
            fields.append(field)

    for f in REQUIRED:
        if not addr.get(f):
            flag(f, f"campo ausente: {f}")
    if addr.get("cep") and not re.fullmatch(r"\d{5}-\d{3}", addr["cep"]):
        flag("cep", "CEP em formato inválido")
    if addr.get("uf") and addr["uf"] not in UFS:
        flag("uf", "UF inválida")
    cidade, bairro = addr.get("cidade", ""), addr.get("bairro", "")
    if cidade and not _CITY_RE.match(cidade):
        flag("cidade", "cidade com conteúdo suspeito")
    if bairro and (not _BAIRRO_RE.match(bairro) or re.search(r"\bCEP\b", bairro)):
        flag("bairro", "bairro com conteúdo suspeito")
    return warnings, fields


def validate_address(addr: dict) -> list[str]:
    return check_fields(addr)[0]


def check_viacep(cep: str, timeout: float = 3.0) -> dict | None:
    """Confere o CEP no ViaCEP (opcional; requer internet). Retorna o JSON ou None."""
    try:
        url = f"https://viacep.com.br/ws/{cep.replace('-', '')}/json/"
        with urllib.request.urlopen(url, timeout=timeout) as r:  # noqa: S310
            data = json.load(r)
        return None if data.get("erro") else data
    except Exception:
        return None
