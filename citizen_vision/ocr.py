"""Etapa 3 — OCR agrupado em linhas com confiança e posição."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pytesseract
from pytesseract import Output


@dataclass
class Line:
    text: str
    conf: float
    box: tuple  # x0, y0, x1, y1


def pick_lang() -> str:
    """Usa 'por' se o pacote de idioma estiver instalado; senão cai para 'eng'."""
    try:
        langs = set(pytesseract.get_languages(config=""))
    except Exception:
        return "eng"
    return "por+eng" if "por" in langs else "eng"


def ocr_lines(img: np.ndarray, lang: str | None = None, psm: int = 6) -> list[Line]:
    lang = lang or pick_lang()
    d = pytesseract.image_to_data(
        img, lang=lang, config=f"--psm {psm}", output_type=Output.DICT
    )
    groups: dict = {}
    for i, txt in enumerate(d["text"]):
        if not txt.strip() or float(d["conf"][i]) < 0:
            continue
        key = (d["block_num"][i], d["par_num"][i], d["line_num"][i])
        groups.setdefault(key, []).append(i)

    lines = []
    for idxs in groups.values():
        idxs.sort(key=lambda i: d["left"][i])
        text = " ".join(d["text"][i] for i in idxs)
        conf = float(np.mean([float(d["conf"][i]) for i in idxs]))
        x0 = min(d["left"][i] for i in idxs)
        y0 = min(d["top"][i] for i in idxs)
        x1 = max(d["left"][i] + d["width"][i] for i in idxs)
        y1 = max(d["top"][i] + d["height"][i] for i in idxs)
        lines.append(Line(text, conf, (x0, y0, x1, y1)))
    lines.sort(key=lambda l: (l.box[1], l.box[0]))
    return lines
