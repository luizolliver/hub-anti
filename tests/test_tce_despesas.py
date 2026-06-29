"""
Testes da Etapa 2A — coletor de Despesas do TCE-SP.

Rodam offline sobre `tests/fixtures/tce_despesas_exemplo.json` (14 linhas reais
de Barretos, jan/2019, capturadas da API REST do TCE). Nenhum acesso à internet.
"""

import json
from pathlib import Path

import pytest

from src.collectors.tce_despesas import parsear_despesas, salvar_despesas
from src.db import init_db
from src.models import (
    Despesa,
    parse_data_br,
    parse_id_fornecedor,
    parse_valor_br,
)

FIXTURE = Path(__file__).parent / "fixtures" / "tce_despesas_exemplo.json"


@pytest.fixture
def rows():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- helpers de parsing -----------------------------------------------------
def test_parse_id_fornecedor_cnpj():
    tipo, doc = parse_id_fornecedor("CNPJ - PESSOA JURÍDICA - 02558157000162")
    assert tipo == "CNPJ"
    assert doc == "02558157000162"


def test_parse_id_fornecedor_pessoa_fisica_mascarado():
    # CPF vem mascarado pelo TCE — não devolvemos documento (LGPD).
    tipo, doc = parse_id_fornecedor("PESSOA FÍSICA - 114968")
    assert tipo == "CPF"
    assert doc is None


def test_parse_id_fornecedor_identificacao_especial():
    tipo, doc = parse_id_fornecedor("IDENTIFICAÇÃO ESPECIAL - SEM CPF/CNPJ - 00000")
    assert tipo == "OUTRO"
    assert doc is None


def test_parse_valor_br():
    assert parse_valor_br("289,61") == 289.61
    assert parse_valor_br("1.582,98") == 1582.98
    assert parse_valor_br("9000,00") == 9000.0
    assert parse_valor_br("") is None


def test_parse_data_br():
    assert parse_data_br("06/01/2019") == "2019-01-06"
    assert parse_data_br("") is None
    assert parse_data_br("xx") is None


# --- parser principal -------------------------------------------------------
def test_parser_retorna_despesas(rows):
    despesas = parsear_despesas(rows)
    assert len(despesas) == len(rows)
    assert all(isinstance(d, Despesa) for d in despesas)
    assert all(d.fonte == "TCE-SP" for d in despesas)


def test_cnpj_extraido_do_id_fornecedor(rows):
    despesas = parsear_despesas(rows)
    cnpjs = [d for d in despesas if d.fornecedor_tipo == "CNPJ"]
    assert cnpjs, "deveria haver fornecedores CNPJ na fixture"
    for d in cnpjs:
        assert d.fornecedor_documento and len(d.fornecedor_documento) == 14


def test_soma_por_evento_confere(rows):
    # Soma manual a partir do bruto vs. soma do parser, por evento.
    esperado = {}
    for r in rows:
        v = parse_valor_br(r["vl_despesa"]) or 0
        esperado[r["evento"]] = round(esperado.get(r["evento"], 0) + v, 2)

    despesas = parsear_despesas(rows)
    obtido = {}
    for d in despesas:
        obtido[d.evento] = round(obtido.get(d.evento, 0) + (d.valor or 0), 2)

    assert obtido == esperado


def test_gravacao_e_dedup(tmp_path, rows):
    conn = init_db(tmp_path / "t.db")
    despesas = parsear_despesas(rows)

    novas1 = salvar_despesas(conn, despesas)
    (total1,) = conn.execute("SELECT COUNT(*) FROM despesas;").fetchone()
    assert novas1 == total1 == len(despesas)

    # Re-coletar o mesmo mês não duplica.
    novas2 = salvar_despesas(conn, despesas)
    (total2,) = conn.execute("SELECT COUNT(*) FROM despesas;").fetchone()
    assert novas2 == 0
    assert total2 == total1
    conn.close()
