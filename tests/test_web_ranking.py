"""Testes da interface web (FastAPI) — tela de ranking, ponta a ponta.

Usa um banco SQLite temporário semeado, apontado por `config.DB_PATH`, e o
TestClient do Starlette. Não sobe servidor nem toca a rede.
"""

import importlib

import pytest
from starlette.testclient import TestClient

import config
from src.db import init_db


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Banco temporário com um fornecedor de nível alto (situação + sanção).
    db = tmp_path / "web.db"
    conn = init_db(db)
    conn.execute(
        "INSERT INTO fornecedores (cnpj, nome, valor_pago, valor_contratos) "
        "VALUES ('09095412000127','ABBC',2264000.0,0.0)"
    )
    conn.execute(
        "INSERT INTO empresas (cnpj, razao_social, situacao_cadastral) "
        "VALUES ('09095412000127','ABBC','INAPTA')"
    )
    conn.execute(
        "INSERT INTO sancoes_encontradas (id, alvo_tipo, alvo_cnpj, fonte, categoria, vinculo) "
        "VALUES ('s','fornecedor','09095412000127','CEIS','Impedimento','cnpj')"
    )
    conn.execute(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio, nome_socio_chave, tipo_socio) "
        "VALUES ('so','09095412000127','HENRIQUE DUARTE PRATA','HENRIQUE DUARTE PRATA','PF')"
    )
    conn.execute(
        "INSERT INTO contratos (id, fonte, id_origem, fornecedor_cnpj, fornecedor_nome, orgao, modalidade, objeto, valor, data, ano) "
        "VALUES ('k1','TCE-SP','2019900000117','09095412000127','ABBC','PREFEITURA','Dispensa','SERVICOS DE SAUDE',500000.0,'2024-05-01','2024')"
    )
    conn.execute(
        "INSERT INTO contratos (id, fonte, id_origem, fornecedor_cnpj, fornecedor_nome, orgao, modalidade, objeto, valor, data, ano) "
        "VALUES ('k2','PNCP','/contratos/44780609000104/2026/69','09095412000127','ABBC','PREFEITURA','Pregao','EQUIPAMENTOS',80000.0,'2026-02-01','2026')"
    )
    conn.commit()
    conn.close()

    monkeypatch.setattr(config, "DB_PATH", db)
    # Recarrega o app para que ele leia o DB_PATH já sobrescrito.
    import web.app as webapp
    importlib.reload(webapp)
    webapp._ranking_cached.cache_clear()
    return TestClient(webapp.app)


def test_index_renderiza(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Ranking de atenção" in r.text
    # FLAGS_META injetado para o front consumir.
    assert "window.FLAGS_META" in r.text
    assert "/static/app.js" in r.text


def test_api_ranking_contrato_de_dados(client):
    r = client.get("/api/ranking?minimo=5")
    assert r.status_code == 200
    data = r.json()
    assert set(data) >= {"count", "minimo", "filtro_ativo", "suppliers", "flags_meta"}
    assert data["minimo"] == 5
    assert data["filtro_ativo"] is False
    assert data["count"] >= 1
    for s in data["suppliers"]:
        assert set(s) == {"lvl", "cnpj", "name", "paid", "flags"}
        assert s["lvl"] >= 5  # respeita o mínimo
    # ABBC: situação(4) + sanção(5) [+ concentração(2), único fornecedor] ≥ 9.
    abbc = next(s for s in data["suppliers"] if s["cnpj"] == "09095412000127")
    assert abbc["lvl"] >= 9
    assert abbc["name"] == "ABBC"
    assert abbc["paid"] == 2264000.0
    assert "SITUACAO_CADASTRAL" in abbc["flags"]
    assert "FORNECEDOR_SANCIONADO" in abbc["flags"]


def test_api_ranking_minimo_alto_esvazia(client):
    r = client.get("/api/ranking?minimo=99")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_api_metricas(client):
    r = client.get("/api/metricas")
    assert r.status_code == 200
    stats = r.json()["stats"]
    labels = {s["label"] for s in stats}
    assert {"Fornecedores", "R$ pago", "Sanções cruzadas"} <= labels
    forn = next(s for s in stats if s["label"] == "Fornecedores")
    assert forn["val"] == 1


def test_api_busca_fornecedor_e_pessoa(client):
    # por nome de empresa
    r = client.get("/api/busca?q=ABBC")
    assert r.status_code == 200
    data = r.json()
    assert data["fornecedores"][0]["cnpj"] == "09095412000127"
    assert data["fornecedores"][0]["lvl"] >= 9  # nível vem do mapa real
    # por nome de sócio
    r2 = client.get("/api/busca?q=HENRIQUE").json()
    assert r2["pessoas"]
    assert r2["pessoas"][0]["empresas"][0]["cnpj"] == "09095412000127"
    # vazio não quebra
    assert client.get("/api/busca?q=").json() == {"fornecedores": [], "pessoas": []}


def test_api_contratos(client):
    r = client.get("/api/contratos?limite=50")
    assert r.status_code == 200
    data = r.json()
    assert data["count"] == 2
    porc = {c["fonte"]: c for c in data["contratos"]}
    assert set(porc["PNCP"]) >= {"data", "orgao", "modalidade", "valor", "objeto",
                                 "fornecedor", "fonte", "link"}
    # PNCP → permalink por registro
    assert porc["PNCP"]["link"]["tipo"] == "registro"
    assert porc["PNCP"]["link"]["url"] == \
        "https://pncp.gov.br/app/contratos/44780609000104/2026/000069"
    # TCE-SP → aponta para o portal da fonte (sem permalink por registro)
    assert porc["TCE-SP"]["link"]["tipo"] == "portal"
    assert "tce.sp.gov.br" in porc["TCE-SP"]["link"]["url"]


def test_api_perfil(client):
    r = client.get("/api/perfil/09095412000127")
    assert r.status_code == 200
    p = r.json()
    assert p["name"] == "ABBC"
    assert p["lvl"] >= 9
    assert "SITUACAO_CADASTRAL" in p["flags"]
    assert p["flags_detail"][0]["peso"] >= 1
    assert p["cad"]["situacao"] == "INAPTA"
    assert p["n_contratos"] == 2
    assert p["sancoes"] and p["sancoes"][0]["fonte"] == "CEIS"
    # sanção por vínculo "cnpj" → busca pré-preenchida pelo CNPJ na fonte
    sl = p["sancoes"][0]["link"]
    assert sl["tipo"] == "busca"
    assert "portaldatransparencia.gov.br" in sl["url"]
    assert "09095412000127" in sl["url"]
    # contratos do perfil trazem link da fonte
    assert all("link" in c for c in p["contratos"])


def test_dossie_html(client):
    r = client.get("/dossie/09095412000127")
    assert r.status_code == 200
    assert "text/html" in r.headers["content-type"]
    assert "Dossiê" in r.text
    assert "09095412000127" in r.text
