import importlib
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("ADMIN_KEY", "segredo-de-teste")
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)  # testes nunca chamam LLM externo
    from app import db
    importlib.reload(db)
    from app import main
    importlib.reload(main)
    from starlette.testclient import TestClient
    with TestClient(main.app) as c:
        yield c


@pytest.fixture
def adm():
    return {"X-API-Key": "segredo-de-teste"}
