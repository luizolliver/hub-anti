"""
Testes da Etapa 1 — coletor PNCP.

Rodam offline sobre a fixture real `tests/fixtures/pncp_exemplo.json`
(10 contratos reais de Barretos capturados da search API do PNCP).
Nenhum teste acessa a internet.
"""

import json
from pathlib import Path

import pytest

from src.collectors.pncp import parsear_pncp, salvar_contratos
from src.db import init_db
from src.models import Contrato

FIXTURE = Path(__file__).parent / "fixtures" / "pncp_exemplo.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_parser_retorna_contratos(payload):
    contratos = parsear_pncp(payload)
    assert len(contratos) == len(payload["items"])
    assert all(isinstance(c, Contrato) for c in contratos)


def test_campos_essenciais_preenchidos(payload):
    contratos = parsear_pncp(payload)
    for c in contratos:
        assert c.id  # numero_controle_pncp
        assert c.fonte == "PNCP"
        assert c.valor is not None and c.valor > 0
        assert c.data  # data_assinatura
        assert c.modalidade
        assert c.orgao
        assert c.municipio_ibge == "3505500"


def test_objeto_vem_de_description(payload):
    contratos = parsear_pncp(payload)
    primeiro_item = payload["items"][0]
    primeiro = next(c for c in contratos if c.id == primeiro_item["numero_controle_pncp"])
    assert primeiro.objeto == primeiro_item["description"]


def test_orgao_cnpj_so_digitos(payload):
    contratos = parsear_pncp(payload)
    for c in contratos:
        if c.orgao_cnpj:
            assert c.orgao_cnpj.isdigit()
            assert len(c.orgao_cnpj) == 14


def test_item_sem_chave_e_ignorado():
    payload = {"items": [{"valor_global": 100}, {"numero_controle_pncp": "X-1/2026", "ano": 2026}]}
    contratos = parsear_pncp(payload)
    assert len(contratos) == 1
    assert contratos[0].id == "X-1/2026"


def test_gravacao_e_dedup(tmp_path, payload):
    conn = init_db(tmp_path / "t.db")
    contratos = parsear_pncp(payload)

    salvar_contratos(conn, contratos)
    (total1,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    assert total1 == len(contratos)

    # Gravar de novo NÃO duplica (upsert por id).
    salvar_contratos(conn, contratos)
    (total2,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    assert total2 == total1
    conn.close()


def test_upsert_preserva_fornecedor_ja_enriquecido(tmp_path, payload):
    # Simula: 1ª gravação sem fornecedor, depois enriquecido, depois nova
    # coleta da search (sem fornecedor) não deve apagar o que já temos.
    conn = init_db(tmp_path / "t.db")
    contratos = parsear_pncp(payload)
    salvar_contratos(conn, [contratos[0]])

    cid = contratos[0].id
    conn.execute(
        "UPDATE contratos SET fornecedor_cnpj=?, fornecedor_nome=? WHERE id=?",
        ("12345678000199", "EMPRESA TESTE LTDA", cid),
    )
    conn.commit()

    # Recoleta da search (fornecedor None) — COALESCE deve preservar.
    salvar_contratos(conn, [contratos[0]])
    row = conn.execute(
        "SELECT fornecedor_cnpj, fornecedor_nome FROM contratos WHERE id=?", (cid,)
    ).fetchone()
    assert row["fornecedor_cnpj"] == "12345678000199"
    assert row["fornecedor_nome"] == "EMPRESA TESTE LTDA"
    conn.close()
