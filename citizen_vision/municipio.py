"""Município do cidadão a partir do endereço da fatura (base para rotear para a prefeitura certa)."""
from __future__ import annotations

from .config import normalize
from .validate import check_viacep


def resolve_municipio(address: dict, online: bool = False, lookup=check_viacep) -> dict:
    """Retorna {municipio, uf, ibge, fonte, confere_cep}.

    Offline: usa cidade/UF lidas da fatura (fonte='fatura', sem código IBGE).
    Online (opcional): confere o CEP no ViaCEP e obtém o código IBGE (fonte='viacep').
    `confere_cep` = False quando o CEP aponta para outra cidade/UF que a fatura.
    """
    out = {"municipio": address.get("cidade", ""), "uf": address.get("uf", ""),
           "ibge": None, "fonte": "fatura", "confere_cep": None}
    cep = address.get("cep", "")
    if online and cep:
        data = lookup(cep)
        if data:
            same = (normalize(data.get("localidade", "")) == normalize(address.get("cidade", ""))
                    and data.get("uf") == address.get("uf"))
            out.update(municipio=normalize(data.get("localidade", "")), uf=data.get("uf", ""),
                       ibge=data.get("ibge"), fonte="viacep", confere_cep=same)
    return out
