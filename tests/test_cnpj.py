"""
Testes da Etapa 4 — enriquecimento societário (CNPJ/QSA).

Rodam offline sobre `tests/fixtures/cnpj_exemplo.json` (resposta real da
BrasilAPI para a Fundação Pio XII). Sem acesso à internet.
"""

import json
from pathlib import Path

import pytest

from src.collectors.cnpj import (
    parsear_empresa,
    parsear_socios,
    precisa_atualizar,
    salvar_empresa,
    salvar_socios,
)
from src.db import init_db

FIXTURE = Path(__file__).parent / "fixtures" / "cnpj_exemplo.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


# --- parse da empresa --------------------------------------------------------
def test_parsear_empresa_campos(payload):
    e = parsear_empresa(payload)
    assert e.cnpj == "49150352000112"
    assert e.cnpj_raiz == "49150352"
    assert e.razao_social == "FUNDACAO PIO XII"
    assert e.situacao_cadastral == "ATIVA"
    assert e.data_inicio_atividade == "1967-11-28"  # base p/ idade da empresa
    assert e.matriz_filial == "MATRIZ"


# --- parse dos sócios --------------------------------------------------------
def test_parsear_socios(payload):
    socios = parsear_socios(payload, "49150352000112")
    assert len(socios) == 3
    nomes = {s.nome_socio for s in socios}
    assert "HENRIQUE DUARTE PRATA" in nomes
    for s in socios:
        assert s.cnpj_empresa == "49150352000112"
        assert s.tipo_socio == "PF"          # identificador_de_socio = 2
        assert s.nome_socio_chave == s.nome_socio  # já sem acento/maiúsculo
        assert s.qualificacao


def test_socio_cpf_mascarado_nao_vira_chave(payload):
    socios = parsear_socios(payload, "49150352000112")
    for s in socios:
        # CPF mascarado é preservado como veio, mas não há cnpj_socio para PF.
        assert s.documento_socio and "*" in s.documento_socio
        assert s.cnpj_socio is None


# --- cache + persistência ----------------------------------------------------
def test_cache_evita_rebusca(tmp_path, payload):
    conn = init_db(tmp_path / "t.db")
    cnpj = "49150352000112"

    # Antes de gravar: precisa atualizar.
    assert precisa_atualizar(conn, cnpj) is True

    salvar_empresa(conn, parsear_empresa(payload))
    salvar_socios(conn, cnpj, parsear_socios(payload, cnpj))

    # Logo após gravar: NÃO precisa rebuscar (cache fresco).
    assert precisa_atualizar(conn, cnpj, dias=30) is False

    # Sócios gravados.
    (n,) = conn.execute("SELECT COUNT(*) FROM socios WHERE cnpj_empresa=?", (cnpj,)).fetchone()
    assert n == 3
    conn.close()


def test_regravar_socios_nao_duplica(tmp_path, payload):
    conn = init_db(tmp_path / "t.db")
    cnpj = "49150352000112"
    socios = parsear_socios(payload, cnpj)
    salvar_socios(conn, cnpj, socios)
    salvar_socios(conn, cnpj, socios)  # regravar
    (n,) = conn.execute("SELECT COUNT(*) FROM socios WHERE cnpj_empresa=?", (cnpj,)).fetchone()
    assert n == 3
    conn.close()
