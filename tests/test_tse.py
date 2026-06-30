"""
Testes da Etapa 8 — doações de campanha (TSE).

Parser roda offline sobre a fixture real (doações a candidatos de Barretos em
2024). O cruzamento usa sócios/fornecedores fabricados a partir de doadores
reais da própria fixture. Sem acesso à internet.
"""

from pathlib import Path

import pytest

from src.collectors.tse import cruzar_doacoes, ler_csv_receitas, parsear_doacoes
from src.db import init_db

FIX = Path(__file__).parent / "fixtures" / "tse_receitas_exemplo.csv"


@pytest.fixture
def doacoes():
    texto = FIX.read_text(encoding="utf-8")
    return parsear_doacoes(ler_csv_receitas(texto))


# --- parser ------------------------------------------------------------------
def test_parser_campos(doacoes):
    assert doacoes
    for d in doacoes:
        assert d.municipio.upper() == "BARRETOS"
        assert d.cargo in ("Prefeito", "Vereador")
        assert d.candidato
    # Há doadores PF (CPF 11) e PJ (CNPJ 14).
    tams = {len(d.doador_documento) for d in doacoes if d.doador_documento}
    assert 11 in tams


def test_valor_e_data(doacoes):
    com_valor = [d for d in doacoes if d.valor is not None]
    assert com_valor
    com_data = [d for d in doacoes if d.data]
    assert all(len(d.data) == 10 and d.data[4] == "-" for d in com_data)


# --- cruzamento doador PF (CPF núcleo + nome) -> sócio -----------------------
def _primeiro_doador_pf(doacoes):
    return next(d for d in doacoes if d.doador_documento and len(d.doador_documento) == 11)


def test_cruza_socio_doador(tmp_path, doacoes):
    conn = init_db(tmp_path / "t.db")
    alvo = _primeiro_doador_pf(doacoes)
    nucleo = alvo.doador_documento[3:9]

    # Sócio de uma empresa de Barretos com mesmo núcleo + mesmo nome do doador.
    conn.execute(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio, documento_socio, "
        "documento_visivel, tipo_socio) VALUES (?, ?, ?, ?, ?, ?)",
        ("s1", "11111111000111", alvo.doador_nome, f"***{nucleo}**", nucleo, "PF"),
    )
    conn.commit()

    achados = cruzar_doacoes(conn, doacoes)
    meus = [a for a in achados if a["alvo_cnpj"] == "11111111000111"]
    assert meus, "deveria casar o sócio doador por núcleo + nome"
    assert meus[0]["alvo_tipo"] == "socio"
    assert meus[0]["vinculo"] == "forte"
    assert meus[0]["candidato"] == alvo.candidato
    conn.close()


def test_nao_casa_nome_diferente_mesmo_nucleo_eh_investigar(tmp_path, doacoes):
    conn = init_db(tmp_path / "t.db")
    alvo = _primeiro_doador_pf(doacoes)
    nucleo = alvo.doador_documento[3:9]
    conn.execute(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio, documento_socio, "
        "documento_visivel, tipo_socio) VALUES (?, ?, ?, ?, ?, ?)",
        ("s1", "22222222000122", "FULANO DE TAL DIFERENTE", f"***{nucleo}**", nucleo, "PF"),
    )
    conn.commit()
    achados = cruzar_doacoes(conn, doacoes)
    meus = [a for a in achados if a["alvo_cnpj"] == "22222222000122"]
    # Mesmo núcleo, nome diferente → investigar (não forte).
    assert all(a["vinculo"] == "investigar" for a in meus)
    conn.close()


# --- cruzamento doador PJ -> fornecedor -------------------------------------
def test_cruza_fornecedor_doador_pj(tmp_path, doacoes):
    pj = next((d for d in doacoes if d.doador_documento and len(d.doador_documento) == 14), None)
    if pj is None:
        pytest.skip("fixture sem doador PJ")
    conn = init_db(tmp_path / "t.db")
    conn.execute("INSERT INTO fornecedores (cnpj, nome) VALUES (?, ?)",
                 (pj.doador_documento, "FORNECEDOR DOADOR"))
    conn.commit()
    achados = cruzar_doacoes(conn, doacoes)
    meus = [a for a in achados if a["alvo_cnpj"] == pj.doador_documento]
    assert meus and meus[0]["alvo_tipo"] == "fornecedor"
    conn.close()
