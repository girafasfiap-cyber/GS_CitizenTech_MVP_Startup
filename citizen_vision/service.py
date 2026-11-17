"""Camada de serviço: bytes de imagem -> resposta JSON do MVP (usada pela API e pelo servidor de demo)."""
from __future__ import annotations

import cv2
import numpy as np

from .municipio import resolve_municipio
from .pipeline import process_image

MAX_BYTES = 8 * 1024 * 1024


class ServiceError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status, self.message = status, message


def extract_from_bytes(data: bytes, lookup_ibge: bool = False) -> dict:
    """Processa em memória (nada é gravado em disco nem logado — LGPD)."""
    if not data:
        raise ServiceError(400, "nenhuma imagem enviada")
    if len(data) > MAX_BYTES:
        raise ServiceError(413, "imagem maior que 8 MB")
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ServiceError(400, "arquivo não é uma imagem válida")
    result = process_image(img)
    out = result.to_dict()
    reliable_city = bool(result.address) and "cidade" not in result.fields_to_check
    out["municipio"] = resolve_municipio(result.address, online=lookup_ibge) if reliable_city else None
    if out["municipio"] and out["municipio"]["confere_cep"] is False:
        out["warnings"].append("CEP não confere com a cidade da fatura")
    return out
