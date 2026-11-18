"""Triagem por IA: sugere a categoria do problema e uma redação formal para a prefeitura.

1) Se OPENROUTER_API_KEY existir, usa o componente de IA Generativa do grupo (app/genai: prompt versionado com exemplos,
   saída JSON validada por schema, até 2 reparos, fallback de modelo, guardrails e resposta segura), via OpenRouter.
2) Se não houver chave, se a chamada demorar mais que LLM_TIMEOUT ou se a saída for inválida, cai para regras lexicais
   (sempre disponível, sem custo). O reporte do cidadão nunca fica bloqueado pela IA.
Responsabilidade: a descrição do cidadão é DADO, nunca instrução; PII é mascarada antes de sair do servidor;
a saída é validada contra a lista fixa de categorias; confiança < LIMIAR manda o reporte para revisão humana.
"""
import csv
import hashlib
import logging
import os
import re
import unicodedata
from concurrent.futures import ThreadPoolExecutor, TimeoutError as PrazoEsgotado
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("triagem")
SEEDS = Path(__file__).resolve().parent.parent / "seeds"
LIMIAR = float(os.getenv("LIMIAR_CONFIANCA_IA", "0.70"))

REGRAS = {
    "pavimento": ["buraco", "asfalto", "cratera", "afundamento", "pavimento", "tapa-buraco", "tapa buraco", "rua esburacada", "esburacad"],
    "iluminacao": ["poste", "lampada", "iluminacao", "luz apagada", "escuro", "fiacao", "fio solto", "apagad"],
    "limpeza_urbana": ["lixo", "entulho", "descarte", "varricao", "sujeira", "mato alto na calcada", "cacamba", "resto de obra", "esgoto a ceu"],
    "arvores_areas_verdes": ["arvore", "galho", "poda", "capinacao", "rocada", "praca", "mato", "tronco"],
    "calcadas_acessibilidade": ["calcada", "rampa", "cadeirante", "acessibilidade", "piso tatil", "meio-fio", "meio fio", "passeio"],
    "sinalizacao_semaforo": ["semaforo", "sinal", "botoeira", "faixa de pedestre", "placa", "sinalizacao", "travessia"],
    "drenagem": ["bueiro", "boca de lobo", "alagamento", "alaga", "enchente", "corrego", "entupid", "galeria", "agua parada"],
}


def _norm(t: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", t.lower()) if unicodedata.category(c) != "Mn")


@lru_cache
def categorias() -> dict:
    with open(SEEDS / "categorias.csv", encoding="utf-8") as f:
        return {r["codigo"]: r for r in csv.DictReader(f)}


def mascarar_pii(t: str) -> str:
    t = re.sub(r"\b\d{3}\.?\d{3}\.?\d{3}-?\d{2}\b", "[CPF]", t)
    t = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[EMAIL]", t)
    t = re.sub(r"(\+?55\s?)?\(?\d{2}\)?\s?9?\d{4}[-\s]?\d{4}\b", "[TELEFONE]", t)
    return t


def por_regras(descricao: str) -> dict:
    n = _norm(descricao)
    pontos = {c: sum(1 for k in ks if k in n) for c, ks in REGRAS.items()}
    ordem = sorted(pontos.items(), key=lambda kv: -kv[1])
    (c1, p1), (_, p2) = ordem[0], ordem[1]
    if p1 == 0:
        return {"categoria": None, "confianca": 0.30, "modelo": "regras-v1", "texto_formal": None}
    conf = min(0.92, 0.50 + 0.12 * p1) - (0.20 if p2 == p1 else 0.0)  # empate entre categorias: menos confiança
    return {"categoria": c1, "confianca": round(max(conf, 0.30), 2), "modelo": "regras-v1", "texto_formal": None}


# Taxonomia do componente de Gen AI -> categorias do MVP (as 7 do SP156). Sem equivalente => None => revisão humana.
MAPA_GENAI = {
    "buraco_via": "pavimento",
    "iluminacao_publica": "iluminacao",
    "lixo_entulho": "limpeza_urbana",
    "arvore_poda": "arvores_areas_verdes",
    "calcada_acessibilidade": "calcadas_acessibilidade",
    "sinalizacao_transito": "sinalizacao_semaforo",
    "agua_esgoto": None,
    "area_rural_estrada": None,
    "outro": None,
}
PRAZO_LLM = float(os.getenv("LLM_TIMEOUT", "15"))  # orçamento total da IA por chamada, em segundos
_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="genai")
_cache: dict[str, dict] = {}
_assistente_unico = None


def _assistente():
    """Cria o Assistente do componente Gen AI uma única vez, com orçamento de tempo curto (padrões do MVP)."""
    global _assistente_unico
    if _assistente_unico is None:
        os.environ.setdefault("REQUEST_TIMEOUT_S", "8")
        os.environ.setdefault("MAX_RETRIES", "1")
        os.environ.setdefault("OPENROUTER_FALLBACK_MODELS", "nvidia/nemotron-3.5-lightning:free")
        from .genai import services as gs
        gs.MAX_REPAIRS = 1
        _assistente_unico = gs.Assistente()
    return _assistente_unico


def por_genai(descricao: str) -> dict | None:
    if not os.getenv("OPENROUTER_API_KEY"):
        return None
    chave = hashlib.sha256(descricao.strip().lower().encode()).hexdigest()
    if chave in _cache:  # o servidor reclassifica ao gravar o reporte; a segunda chamada sai do cache
        return dict(_cache[chave])
    try:
        resp = _pool.submit(lambda: _assistente().triar(descricao)).result(timeout=PRAZO_LLM)
    except PrazoEsgotado:
        log.warning("IA excedeu %.0fs, usando regras", PRAZO_LLM)
        return None
    except Exception as e:  # sem chave válida, rede, modelo indisponível...
        log.warning("IA indisponível, usando regras: %s", e)
        return None
    if resp.meta.fallback_seguro:  # o componente de IA devolveu a resposta de contingência: as regras fazem melhor
        return None
    r = resp.resultado
    cat = MAPA_GENAI.get(r.categoria.value)
    out = {
        "categoria": cat,
        "confianca": round(r.confianca, 2) if cat else min(round(r.confianca, 2), 0.5),
        "modelo": resp.meta.modelo or "genai",
        "texto_formal": r.resumo[:600],
        "prioridade": r.prioridade.value,
        "risco_imediato": r.risco_imediato,
        "orgao": r.orgao_responsavel,
        "dados_faltantes": r.dados_faltantes,
        "revisao_genai": r.revisao_humana,
    }
    if len(_cache) > 500:
        _cache.clear()
    _cache[chave] = out
    return dict(out)


def classificar(descricao: str) -> dict:
    r = por_genai(descricao) or por_regras(descricao)
    r["requer_revisao"] = r["categoria"] is None or r["confianca"] < LIMIAR or bool(r.get("revisao_genai"))
    return r
