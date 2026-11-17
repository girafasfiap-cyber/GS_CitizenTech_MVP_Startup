"""Etapa 4 — identificar qual empresa emitiu o documento (por palavras-chave do OCR)."""
from __future__ import annotations

from difflib import get_close_matches

from .config import COMPANIES, normalize


def _kw_score(keyword: str, text: str, tokens: list[str]) -> float:
    if keyword in text:
        return 1.0
    if " " not in keyword and len(keyword) >= 4 and get_close_matches(keyword, tokens, n=1, cutoff=0.85):
        return 0.8  # tolerância a erro de OCR (ex.: SABE5P)
    return 0.0


def classify_company(lines) -> tuple[str | None, float]:
    """Retorna (chave_da_empresa, confiança 0-1). None se nenhuma bateu."""
    text = normalize(" ".join(l.text for l in lines))
    tokens = text.split()
    scores = {
        key: sum(_kw_score(kw, text, tokens) for kw in comp.keywords)
        for key, comp in COMPANIES.items()
    }
    best = max(scores, key=scores.get)
    total = sum(scores.values())
    if scores[best] < 1.0:
        return None, 0.0
    return best, round(scores[best] / total, 3)
