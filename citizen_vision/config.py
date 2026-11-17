"""Configuração por empresa (templates) e utilidades de normalização."""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass


def normalize(text: str) -> str:
    """MAIÚSCULAS, sem acentos, espaços e traços unificados (padrão Correios)."""
    t = unicodedata.normalize("NFKD", text)
    t = "".join(c for c in t if not unicodedata.combining(c))
    t = t.replace("–", "-").replace("—", "-").replace("_", " ")
    return re.sub(r"\s+", " ", t.upper()).strip()


UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG",
    "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}


@dataclass(frozen=True)
class Company:
    key: str
    display: str
    keywords: tuple          # palavras que identificam a empresa no texto
    anchor: str              # rótulo do endereço CORRETO (normalizado)
    layout: str              # estratégia de parsing: multiline | street_bairro | inline


COMPANIES = {
    "enel": Company(
        "enel", "Enel (energia)",
        ("ENEL", "ENERGIA ELETRICA", "UNIDADE CONSUMIDORA", "KWH"),
        "ENDERECO DA UNIDADE CONSUMIDORA", "multiline",
    ),
    "sabesp": Company(
        "sabesp", "Sabesp (água)",
        ("SABESP", "AGUA E ESGOTO", "HIDROMETRO", "ESGOTO"),
        "ENDERECO DO IMOVEL", "street_bairro",
    ),
    "claro": Company(
        "claro", "Claro (telecom)",
        ("CLARO", "INTERNET", "FATURA CLARO", "MBPS"),
        "ENDERECO DE ENTREGA DA FATURA", "inline",
    ),
}

# Rótulos de endereços que NÃO queremos (iscas) — servem como "stop" na coleta.
DECOY_LABELS = ("ENDERECO DE COBRANCA", "ENDERECO DA SEDE", "SEDE")
