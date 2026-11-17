"""Etapa 1 — localizar a folha na foto e corrigir a perspectiva."""
from __future__ import annotations

import cv2
import numpy as np

OUT_WIDTH = 1240  # largura padrão da folha retificada (A4 a ~150 dpi)


def order_points(pts) -> np.ndarray:
    """Ordena 4 pontos como: topo-esq, topo-dir, base-dir, base-esq."""
    pts = np.array(pts, dtype="float32").reshape(4, 2)
    s = pts.sum(axis=1)
    d = np.diff(pts, axis=1).ravel()
    return np.array(
        [pts[np.argmin(s)], pts[np.argmin(d)], pts[np.argmax(s)], pts[np.argmax(d)]],
        dtype="float32",
    )


def find_document_quad(img: np.ndarray):
    """Retorna os 4 cantos da folha (coords da imagem original) ou None."""
    h, w = img.shape[:2]
    scale = 1000.0 / max(h, w) if max(h, w) > 1000 else 1.0
    small = cv2.resize(img, None, fx=scale, fy=scale) if scale != 1.0 else img
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (7, 7), 0)
    _, th = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, np.ones((15, 15), np.uint8))
    contours, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None
    c = max(contours, key=cv2.contourArea)
    if cv2.contourArea(c) < 0.2 * small.shape[0] * small.shape[1]:
        return None
    approx = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
    quad = approx.reshape(4, 2) if len(approx) == 4 else cv2.boxPoints(cv2.minAreaRect(c))
    return order_points(quad / scale)


def warp_document(img: np.ndarray, quad: np.ndarray) -> np.ndarray:
    tl, tr, br, bl = quad
    width = max(np.linalg.norm(tr - tl), np.linalg.norm(br - bl))
    height = max(np.linalg.norm(bl - tl), np.linalg.norm(br - tr))
    out_w = OUT_WIDTH
    out_h = int(round(out_w * height / width))
    dst = np.array([[0, 0], [out_w - 1, 0], [out_w - 1, out_h - 1], [0, out_h - 1]], dtype="float32")
    m = cv2.getPerspectiveTransform(quad, dst)
    return cv2.warpPerspective(img, m, (out_w, out_h), flags=cv2.INTER_CUBIC)


def rectify(img: np.ndarray):
    """Devolve (imagem retificada, encontrou_documento)."""
    quad = find_document_quad(img)
    if quad is None:
        h, w = img.shape[:2]
        scale = OUT_WIDTH / w
        return cv2.resize(img, None, fx=scale, fy=scale), False
    return warp_document(img, quad), True
