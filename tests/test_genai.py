"""Integração do componente de IA Generativa (app/genai) com a triagem do MVP, sem chamar a rede."""
import time

import pytest

from app import triagem
from app.genai.schemas import Categoria, Localizacao, Meta, Prioridade, TriagemResponse, TriagemResult


def _resp(cat, conf=0.9, risco=False, revisao=False, fallback=False):
    r = TriagemResult(
        categoria=cat, prioridade=Prioridade.urgente if risco else Prioridade.media,
        orgao_responsavel="Secretaria de Infraestrutura / Obras", resumo="Buraco grande na via, perto do número 100.",
        localizacao=Localizacao(), risco_imediato=risco, justificativa_prioridade="Teste de integração.",
        confianca=conf, revisao_humana=revisao,
    )
    return TriagemResponse(resultado=r, meta=Meta(modelo="modelo-teste", fallback_seguro=fallback))


class Falso:
    def __init__(self, resp=None, erro=None, espera=0):
        self.resp, self.erro, self.espera, self.chamadas = resp, erro, espera, 0

    def triar(self, relato):
        self.chamadas += 1
        time.sleep(self.espera)
        if self.erro:
            raise self.erro
        return self.resp


@pytest.fixture(autouse=True)
def ambiente(monkeypatch):
    monkeypatch.setenv("OPENROUTER_API_KEY", "chave-de-teste")
    triagem._cache.clear()


def usar(monkeypatch, falso):
    monkeypatch.setattr(triagem, "_assistente", lambda: falso)
    return falso


def test_mapeia_categoria_do_genai_para_a_do_mvp(monkeypatch):
    usar(monkeypatch, Falso(_resp(Categoria.buraco_via)))
    r = triagem.classificar("buraco enorme na rua das flores")
    assert r["categoria"] == "pavimento" and r["modelo"] == "modelo-teste"
    assert r["texto_formal"].startswith("Buraco grande") and r["prioridade"] == "media"
    assert r["requer_revisao"] is False
    assert r["categoria"] in triagem.categorias()  # a saída sempre cai nas categorias do banco


def test_todas_as_categorias_mapeadas_existem_no_mvp():
    for destino in triagem.MAPA_GENAI.values():
        assert destino is None or destino in triagem.categorias()
    assert {c.value for c in Categoria} == set(triagem.MAPA_GENAI)  # nenhuma categoria do genai ficou sem mapa


@pytest.mark.parametrize("cat", [Categoria.outro, Categoria.agua_esgoto, Categoria.area_rural_estrada])
def test_sem_equivalente_vai_para_revisao_humana(monkeypatch, cat):
    usar(monkeypatch, Falso(_resp(cat, conf=0.95, revisao=cat == Categoria.outro)))
    r = triagem.classificar("relato qualquer")
    assert r["categoria"] is None and r["requer_revisao"] is True and r["confianca"] <= 0.5


def test_confianca_abaixo_do_limiar_do_mvp_exige_revisao(monkeypatch):
    usar(monkeypatch, Falso(_resp(Categoria.iluminacao_publica, conf=0.65)))  # o genai aceitaria (0,6), o MVP não (0,70)
    r = triagem.classificar("poste apagado")
    assert r["categoria"] == "iluminacao" and r["requer_revisao"] is True


def test_risco_imediato_e_prioridade_urgente_chegam_ao_mvp(monkeypatch):
    usar(monkeypatch, Falso(_resp(Categoria.arvore_poda, risco=True)))
    r = triagem.classificar("árvore prestes a cair na escola")
    assert r["risco_imediato"] is True and r["prioridade"] == "urgente"


def test_erro_do_modelo_cai_para_regras(monkeypatch):
    usar(monkeypatch, Falso(erro=RuntimeError("provedor fora do ar")))
    r = triagem.classificar("buraco enorme na rua")
    assert r["modelo"] == "regras-v1" and r["categoria"] == "pavimento"


def test_resposta_segura_do_genai_cai_para_regras(monkeypatch):
    usar(monkeypatch, Falso(_resp(Categoria.outro, conf=0.0, revisao=True, fallback=True)))
    assert triagem.classificar("bueiro entupido")["modelo"] == "regras-v1"


def test_demora_alem_do_prazo_cai_para_regras(monkeypatch):
    monkeypatch.setattr(triagem, "PRAZO_LLM", 0.2)
    usar(monkeypatch, Falso(_resp(Categoria.buraco_via), espera=1.0))
    assert triagem.classificar("poste sem luz")["modelo"] == "regras-v1"


def test_segunda_chamada_igual_usa_cache(monkeypatch):
    f = usar(monkeypatch, Falso(_resp(Categoria.buraco_via)))
    triagem.classificar("buraco enorme na rua das flores")
    triagem.classificar("  Buraco enorme na rua das flores ")
    assert f.chamadas == 1


def test_sem_chave_usa_regras_sem_chamar_o_genai(monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY")
    f = usar(monkeypatch, Falso(_resp(Categoria.buraco_via)))
    assert triagem.classificar("buraco na rua")["modelo"] == "regras-v1" and f.chamadas == 0
