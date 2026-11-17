"""Etapa 2 — pré-processamento para OCR."""
from __future__ import annotations

import cv2
import numpy as np


def remove_shadows(gray: np.ndarray) -> np.ndarray:
    """Divide pela estimativa do fundo: elimina gradientes de iluminação/sombra."""
    bg = cv2.medianBlur(cv2.dilate(gray, np.ones((7, 7), np.uint8)), 21)
    diff = 255 - cv2.absdiff(gray, bg)
    return cv2.normalize(diff, None, 0, 255, cv2.NORM_MINMAX)


def estimate_skew(binary_inv: np.ndarray, limit: float = 6.0, step: float = 0.5) -> float:
    """Ângulo residual por perfil de projeção horizontal (máxima variância)."""
    small = cv2.resize(binary_inv, None, fx=0.4, fy=0.4, interpolation=cv2.INTER_AREA)
    h, w = small.shape
    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-limit, limit + step, step):
        m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
        rot = cv2.warpAffine(small, m, (w, h), flags=cv2.INTER_NEAREST)
        score = float(np.var(rot.sum(axis=1)))
        if score > best_score:
            best_angle, best_score = float(angle), score
    return best_angle


def rotate(img: np.ndarray, angle: float, border: int = 255) -> np.ndarray:
    if abs(angle) < 0.1:
        return img
    h, w = img.shape[:2]
    m = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    return cv2.warpAffine(img, m, (w, h), flags=cv2.INTER_CUBIC, borderValue=border)


def preprocess(bgr: np.ndarray) -> dict:
    """Retorna {'gray', 'enhanced', 'binary', 'skew'}; 'enhanced' é o que vai pro OCR."""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    flat = remove_shadows(gray)
    _, binary_inv = cv2.threshold(flat, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    skew = estimate_skew(binary_inv)
    flat = rotate(flat, skew)
    enhanced = cv2.fastNlMeansDenoising(flat, None, h=7, templateWindowSize=7, searchWindowSize=21)
    binary = cv2.adaptiveThreshold(
        enhanced, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 15
    )
    return {"gray": gray, "enhanced": enhanced, "binary": binary, "skew": skew}
