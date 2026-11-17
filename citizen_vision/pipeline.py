"""Pipeline completo: foto -> empresa + endereço estruturado + sinal de revisão."""
from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field

import cv2
import numpy as np

from .classify import classify_company
from .document import rectify
from .extract import extract_address
from .ocr import ocr_lines
from .preprocess import preprocess
from .validate import check_fields

REVIEW_CONF_THRESHOLD = 0.70


@dataclass
class ExtractionResult:
    company: str | None = None
    company_confidence: float = 0.0
    document_found: bool = False
    address: dict = field(default_factory=dict)
    address_lines: list = field(default_factory=list)
    ocr_confidence: float = 0.0
    warnings: list = field(default_factory=list)
    fields_to_check: list = field(default_factory=list)  # campos que o cidadão deve conferir com atenção
    needs_review: bool = True   # humano no circuito: o MVP sempre pede confirmação
    timings_ms: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


def _load(image) -> np.ndarray:
    if isinstance(image, np.ndarray):
        return image
    img = cv2.imread(str(image))
    if img is None:
        raise ValueError(f"não foi possível ler a imagem: {image}")
    return img


def process_image(image, lang: str | None = None, debug_dir: str | None = None) -> ExtractionResult:
    """`image`: caminho ou array BGR. Não grava nada em disco (exceto debug_dir, opcional)."""
    res = ExtractionResult()
    t0 = time.perf_counter()
    img = _load(image)

    page, res.document_found = rectify(img)
    t1 = time.perf_counter()
    prep = preprocess(page)
    t2 = time.perf_counter()
    lines = ocr_lines(prep["enhanced"], lang=lang)
    t3 = time.perf_counter()

    res.company, res.company_confidence = classify_company(lines)
    if res.company is None:
        res.warnings.append("empresa não reconhecida")
    else:
        res.address, res.address_lines, res.ocr_confidence = extract_address(lines, res.company)
        if not res.address:
            res.warnings.append("rótulo do endereço não encontrado")
        else:
            w, res.fields_to_check = check_fields(res.address)
            res.warnings += w

    if not res.document_found:
        res.warnings.append("bordas do documento não detectadas (usando imagem inteira)")
    if res.ocr_confidence and res.ocr_confidence < REVIEW_CONF_THRESHOLD:
        res.warnings.append("baixa confiança do OCR")

    res.timings_ms = {
        "retificacao": round((t1 - t0) * 1000), "preprocessamento": round((t2 - t1) * 1000),
        "ocr": round((t3 - t2) * 1000), "total": round((time.perf_counter() - t0) * 1000),
    }
    if debug_dir:
        os.makedirs(debug_dir, exist_ok=True)
        cv2.imwrite(os.path.join(debug_dir, "1_retificada.png"), page)
        cv2.imwrite(os.path.join(debug_dir, "2_ocr_input.png"), prep["enhanced"])
        cv2.imwrite(os.path.join(debug_dir, "3_binaria.png"), prep["binary"])
    return res
