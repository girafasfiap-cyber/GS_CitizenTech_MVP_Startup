from app import geocode


def test_cep_preenche_endereco(client, monkeypatch):
    geocode.viacep.cache_clear()
    monkeypatch.setattr(geocode, "_http_json", lambda url: {"cep": "01310-100", "logradouro": "Avenida Paulista", "bairro": "Bela Vista", "localidade": "São Paulo", "uf": "SP"})
    r = client.get("/api/cep/01310-100")
    assert r.status_code == 200
    assert r.json() == {"cep": "01310-100", "logradouro": "Avenida Paulista", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP"}


def test_cep_invalido_e_inexistente(client, monkeypatch):
    geocode.viacep.cache_clear()
    assert client.get("/api/cep/123").status_code == 400
    monkeypatch.setattr(geocode, "_http_json", lambda url: {"erro": True})
    assert client.get("/api/cep/00000000").status_code == 404


def test_cep_servico_fora_do_ar_nao_derruba(client, monkeypatch):
    geocode.viacep.cache_clear()
    def cai(url): raise OSError("sem rede")
    monkeypatch.setattr(geocode, "_http_json", cai)
    assert client.get("/api/cep/01310100").status_code == 404


def test_localizacao_vira_endereco(client, monkeypatch):
    geocode._REVERSO.clear()
    monkeypatch.setattr(geocode, "_http_json", lambda url: {"address": {"road": "Avenida Paulista", "house_number": "1000", "suburb": "Bela Vista",
                                                                         "city": "São Paulo", "ISO3166-2-lvl4": "BR-SP", "postcode": "01310-100"}})
    r = client.get("/api/geocode?lat=-23.56&lon=-46.65")
    assert r.status_code == 200
    assert r.json() == {"logradouro": "Avenida Paulista", "numero": "1000", "bairro": "Bela Vista", "cidade": "São Paulo", "uf": "SP", "cep": "01310-100"}


def test_geocode_valida_coordenadas(client):
    assert client.get("/api/geocode?lat=abc&lon=1").status_code == 400
    assert client.get("/api/geocode?lat=999&lon=1").status_code == 400
