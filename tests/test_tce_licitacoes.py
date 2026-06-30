"""
Testes da Etapa 2B — coletor de Ajustes (contratos) do TCE-SP.

Rodam offline sobre `tests/fixtures/tce_ajustes_exemplo.csv` (linhas reais de
Barretos do arquivo 'ajustes-2019', nível de item). Nenhum acesso à internet.
"""

import csv
import io
from pathlib import Path

import pytest

from src.collectors.tce_licitacoes import _ano_da_url, parsear_ajustes
from src.collectors.pncp import salvar_contratos
from src.db import init_db
from src.models import Contrato

FIXTURE = Path(__file__).parent / "fixtures" / "tce_ajustes_exemplo.csv"


@pytest.fixture
def linhas():
    texto = FIXTURE.read_text(encoding="utf-8")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def _por_codigo(contratos, codigo):
    return next(c for c in contratos if c.id == f"TCE-{codigo}")


# --- parser principal -------------------------------------------------------
def test_parser_retorna_contratos_tce(linhas):
    contratos = parsear_ajustes(linhas)
    assert contratos, "a fixture deveria gerar contratos"
    assert all(isinstance(c, Contrato) for c in contratos)
    assert all(c.fonte == "TCE-SP" for c in contratos)
    assert all(c.id.startswith("TCE-") for c in contratos)


def test_dedup_por_codigo_do_ajuste(linhas):
    # Duplicar uma linha não cria contrato extra (dedup pela chave canônica).
    contratos = parsear_ajustes(linhas + [linhas[0]])
    ids = [c.id for c in contratos]
    assert len(ids) == len(set(ids))
    assert len(contratos) == len({(ln["Código do Ajuste"]) for ln in linhas})


def test_cnpj_so_digitos(linhas):
    contratos = parsear_ajustes(linhas)
    cnpjs = [c.fornecedor_cnpj for c in contratos if c.fornecedor_cnpj]
    assert cnpjs, "deveria haver fornecedores com CNPJ"
    assert all(d.isdigit() and len(d) == 14 for d in cnpjs)


def test_contrato_com_valor_total(linhas):
    # CPFL — instrumento Contrato, valor total preenchido.
    c = _por_codigo(parsear_ajustes(linhas), "2019900000115")
    assert c.fornecedor_cnpj == "33050196000188"
    assert c.valor == 91200.0
    assert c.data == "2018-12-13"  # vigência - data assinatura
    assert c.orgao == "CÂMARA MUNICIPAL DE BARRETOS"
    assert c.ano == "2018"


def test_ajuste_nota_empenho_cai_para_valor_da_nota(linhas):
    # Pregão por Nota de Empenho: contrato vazio -> valor/data vêm da nota.
    c = _por_codigo(parsear_ajustes(linhas), "2019900000117")
    assert c.fornecedor_cnpj == "05808979000142"
    assert c.valor == 200.0  # Valor da Nota de Empenho
    assert c.data == "2019-01-29"  # Data da Nota de Empenho
    assert c.modalidade == "Pregao Presencial"


def test_municipio_e_uf(linhas):
    contratos = parsear_ajustes(linhas, municipio_ibge="3505500")
    assert all(c.municipio_ibge == "3505500" for c in contratos)
    assert all(c.uf == "SP" for c in contratos)
    assert all((c.municipio_nome or "").upper() == "BARRETOS" for c in contratos)


def test_objeto_preenchido(linhas):
    # Mesmo nos ajustes de nota de empenho (sem 'objeto contratado'), há objeto
    # via fallback para a descrição/objeto da licitação.
    contratos = parsear_ajustes(linhas)
    assert all(c.objeto for c in contratos)


# --- gravação reutiliza o upsert do PNCP ------------------------------------
def test_gravacao_e_dedup(tmp_path, linhas):
    conn = init_db(tmp_path / "t.db")
    contratos = parsear_ajustes(linhas)

    salvar_contratos(conn, contratos)
    (total1,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    assert total1 == len(contratos)

    # Re-gravar não duplica (upsert por id).
    salvar_contratos(conn, contratos)
    (total2,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    assert total2 == total1

    (tce,) = conn.execute("SELECT COUNT(*) FROM contratos WHERE fonte='TCE-SP';").fetchone()
    assert tce == len(contratos)
    conn.close()


# --- helper de URL ----------------------------------------------------------
def test_ano_da_url():
    assert _ano_da_url(".../ajustes-2019_0.zip") == "2019"
    assert _ano_da_url(".../ajustes-2024-1o-semestre.zip") == "2024"
    assert _ano_da_url(".../licitacoes-2020.zip") is None
