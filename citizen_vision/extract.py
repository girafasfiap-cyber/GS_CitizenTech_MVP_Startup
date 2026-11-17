"""Etapa 5 — achar o endereço CORRETO (entre vários na fatura) e estruturá-lo."""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .config import COMPANIES, DECOY_LABELS, normalize

_DIGIT_FIX = str.maketrans({"O": "0", "I": "1", "L": "1", "S": "5", "B": "8"})
CEP_RE = re.compile(r"CEP[:\s]*([0-9OILSB]{5})\s*-?\s*([0-9OILSB]{3})\b")
CEP_FALLBACK_RE = re.compile(r"\b(\d{5})\s*-?\s*(\d{3})\b")
STREET_NUM_RE = re.compile(r"^(?P<street>.+?)\s*,\s*(?P<num>\d+[A-Z]?|S/?N)\b")


def _label_score(label: str, line: str) -> float:
    if label in line:
        return 1.0
    m = SequenceMatcher(None, label, line, autojunk=False).find_longest_match(0, len(label), 0, len(line))
    return m.size / len(label)


def _all_labels() -> list[str]:
    return [c.anchor for c in COMPANIES.values()] + list(DECOY_LABELS)


def find_cep(text: str) -> str | None:
    t = normalize(text)
    m = CEP_RE.search(t)
    if m:
        digits = (m.group(1) + m.group(2)).translate(_DIGIT_FIX)
        return f"{digits[:5]}-{digits[5:]}"
    m = CEP_FALLBACK_RE.search(t)
    return f"{m.group(1)}-{m.group(2)}" if m else None


def collect_address_lines(lines, anchor: str, max_lines: int = 6, min_score: float = 0.8):
    """Localiza o rótulo do endereço certo e coleta as linhas seguintes até o CEP.

    Retorna (lista_de_linhas_normalizadas, confiança_média_do_OCR) ou ([], 0).
    """
    norm = [normalize(l.text) for l in lines]
    scores = [_label_score(anchor, n) for n in norm]
    if not scores or max(scores) < min_score:
        return [], 0.0
    start = max(range(len(scores)), key=scores.__getitem__)

    collected, confs = [], []
    if anchor in norm[start]:  # texto na mesma linha do rótulo
        rest = norm[start].split(anchor, 1)[1].strip(" :-")
        if rest:
            collected.append(rest)
            confs.append(lines[start].conf)

    other_labels = [lb for lb in _all_labels() if lb != anchor]
    for j in range(start + 1, min(start + 1 + max_lines, len(norm))):
        if any(_label_score(lb, norm[j]) >= min_score for lb in other_labels):
            break
        collected.append(norm[j])
        confs.append(lines[j].conf)
        if find_cep(norm[j]):
            break
    return collected, (sum(confs) / len(confs) if confs else 0.0)


# ---------- parsers por layout ----------

def _split_street(text: str) -> tuple[str, str]:
    m = STREET_NUM_RE.match(text)
    if m:
        return m.group("street").strip(), m.group("num")
    return text.strip(), ""


def _find_uf(text: str) -> str:
    from .config import UFS
    cands = re.findall(r"(?:-|/|,)\s*([A-Z]{2})\b", text)
    cands = [c for c in cands if c in UFS]
    return cands[-1] if cands else ""



_UF_FIX = str.maketrans({")": "J", "]": "J", "}": "J", "|": "I", "1": "I", "0": "O", "5": "S"})


def _clean_uf(token: str) -> str:
    """Corrige ruído de OCR em UF (ex.: 'R)' -> 'RJ'). Retorna '' se não der para validar."""
    from difflib import get_close_matches
    from .config import UFS
    t = re.sub(r"[^A-Z]", "", token.upper().translate(_UF_FIX))
    if t in UFS:
        return t
    m = get_close_matches(t, sorted(UFS), n=1, cutoff=0.5) if len(t) == 2 else []
    return m[0] if m else ""


def _split_city_uf(text: str) -> tuple[str, str]:
    """'RIO DE JANEIRO/RJ' ou 'CAMPINAS - SP' -> (cidade, uf)."""
    m = re.match(r"^(.*?)\s*[-/]\s*(\S{1,3})\s*$", text.strip())
    if not m:
        return text.strip(), ""
    return m.group(1).strip(" -"), _clean_uf(m.group(2))


def _strip_cep(text: str) -> str:
    return re.sub(r"CEP[:\s]*[0-9OILSB]{5}\s*-?\s*[0-9OILSB]{3}", "", text).strip(" -/,")


def parse_multiline(lines: list[str]) -> dict:
    """RUA X, 123 / BAIRRO / CIDADE - UF / CEP 00000-000"""
    idx = next((i for i, l in enumerate(lines) if find_cep(l)), len(lines) - 1)
    city_line = lines[idx - 1] if idx >= 1 else ""
    bairro = lines[idx - 2] if idx >= 2 else ""
    street_line = " ".join(lines[: max(idx - 2, 1)])
    street, num = _split_street(street_line)
    city, uf = _split_city_uf(city_line)
    return dict(logradouro=street, numero=num, bairro=bairro, cidade=city, uf=uf,
                cep=find_cep(" ".join(lines)) or "")


def parse_street_bairro(lines: list[str]) -> dict:
    """RUA X, 123 - BAIRRO / CEP 00000-000 - CIDADE/UF"""
    first = lines[0] if lines else ""
    head, _, bairro = first.partition(" - ")
    street, num = _split_street(head)
    last = lines[-1] if len(lines) > 1 else ""
    city, uf = _split_city_uf(_strip_cep(last))
    return dict(logradouro=street, numero=num, bairro=bairro.strip(), cidade=city, uf=uf,
                cep=find_cep(" ".join(lines)) or "")


def parse_inline(lines: list[str]) -> dict:
    """RUA X, 123, COMPL / BAIRRO - CIDADE - UF - CEP 00000-000"""
    street, num = _split_street(lines[0]) if lines else ("", "")
    last = lines[-1] if len(lines) > 1 else ""
    parts = [p.strip() for p in _strip_cep(last).split(" - ") if p.strip()]
    bairro = parts[0] if len(parts) > 0 else ""
    city = parts[1] if len(parts) > 1 else ""
    uf = _clean_uf(parts[2]) if len(parts) > 2 else _find_uf(last)
    return dict(logradouro=street, numero=num, bairro=bairro, cidade=city, uf=uf,
                cep=find_cep(" ".join(lines)) or "")


PARSERS = {"multiline": parse_multiline, "street_bairro": parse_street_bairro, "inline": parse_inline}


def extract_address(lines, company_key: str):
    """Retorna (dict_endereco, linhas_brutas, confiança_ocr_0-1)."""
    comp = COMPANIES[company_key]
    raw, conf = collect_address_lines(lines, comp.anchor)
    if not raw:
        return {}, [], 0.0
    return PARSERS[comp.layout](raw), raw, round(conf / 100.0, 3)
