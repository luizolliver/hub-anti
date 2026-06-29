"""
Testes da Etapa 5 — sanções (CEIS/CNEP) + idade da empresa.

Parser roda offline sobre fixtures reais (recortes do CEIS/CNEP com
fornecedores de Barretos que realmente constam nas listas). O cruzamento
usa um banco-fixture montado no teste. Sem acesso à internet.
"""

from pathlib import Path

import pytest

from src.collectors.sancoes import (
    cruzar_sancoes,
    idade_empresa_meses,
    ler_csv_sancoes,
    parsear_sancoes,
)
from src.db import init_db

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def sancoes_ceis():
    texto = (FIX / "ceis_exemplo.csv").read_text(encoding="utf-8")
    return parsear_sancoes(ler_csv_sancoes(texto), "CEIS")


# --- parser ------------------------------------------------------------------
def test_parser_extrai_campos(sancoes_ceis):
    assert sancoes_ceis
    for s in sancoes_ceis:
        assert s.fonte == "CEIS"
        assert s.documento and s.documento.isdigit()
        assert s.nome_sancionado
        assert s.categoria
    # Há ao menos um CNPJ (14) e um CPF (11) na fixture.
    tamanhos = {len(s.documento) for s in sancoes_ceis}
    assert 14 in tamanhos
    assert 11 in tamanhos


def test_data_em_iso(sancoes_ceis):
    com_data = [s for s in sancoes_ceis if s.data_inicio]
    assert com_data
    for s in com_data:
        # AAAA-MM-DD
        assert len(s.data_inicio) == 10 and s.data_inicio[4] == "-"


# --- idade da empresa --------------------------------------------------------
def test_idade_empresa_meses():
    assert idade_empresa_meses("2020-01-15", "2023-01-15") == 36
    assert idade_empresa_meses("2020-01-15", "2023-01-10") == 35  # dia anterior
    assert idade_empresa_meses("2024-01-01", "2024-04-01") == 3
    assert idade_empresa_meses(None, "2023-01-01") is None
    assert idade_empresa_meses("xx", "2023-01-01") is None


# --- cruzamento por CNPJ (fornecedor) ---------------------------------------
def test_cruza_fornecedor_por_cnpj(tmp_path, sancoes_ceis):
    conn = init_db(tmp_path / "t.db")
    # ABBC e FLORIPARK constam na fixture do CEIS e são fornecedores de Barretos.
    conn.executemany(
        "INSERT INTO fornecedores (cnpj, nome) VALUES (?, ?)",
        [("09095412000127", "ABBC"), ("82889304000116", "FLORIPARK")],
    )
    conn.commit()

    achados = cruzar_sancoes(conn, sancoes_ceis)
    alvos = {a["alvo_cnpj"] for a in achados if a["alvo_tipo"] == "fornecedor"}
    assert "09095412000127" in alvos
    assert "82889304000116" in alvos
    for a in achados:
        if a["alvo_tipo"] == "fornecedor":
            assert a["vinculo"] == "cnpj"

    # Persistiu em sancoes_encontradas.
    (n,) = conn.execute(
        "SELECT COUNT(*) FROM sancoes_encontradas WHERE alvo_tipo='fornecedor'"
    ).fetchone()
    assert n >= 2
    conn.close()


# --- cruzamento por CPF (sócio PF) via núcleo + nome ------------------------
def test_cruza_socio_pf_por_nucleo_e_nome(tmp_path, sancoes_ceis):
    conn = init_db(tmp_path / "t.db")
    # Um sancionado PF da fixture: EDNALDO DE SOUSA LIMA, CPF 00809549441.
    sanc_pf = next(s for s in sancoes_ceis if s.documento == "00809549441")
    nucleo = sanc_pf.documento[3:9]  # 6 dígitos do meio

    # Inserir um sócio com CPF mascarado de mesmo núcleo e mesmo nome.
    conn.execute(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio, nome_socio_chave, "
        "documento_socio, documento_visivel, tipo_socio) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        ("s1", "11111111000111", sanc_pf.nome_sancionado, None,
         f"***{nucleo}**", nucleo, "PF"),
    )
    conn.commit()

    achados = cruzar_sancoes(conn, sancoes_ceis)
    pf = [a for a in achados if a["alvo_tipo"] == "socio_pf"]
    assert pf, "deveria casar o sócio PF sancionado por núcleo + nome"
    assert pf[0]["alvo_cnpj"] == "11111111000111"
    assert pf[0]["vinculo"] == "forte"
    conn.close()
