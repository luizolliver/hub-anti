"""Testes da Etapa 10 — funções de consulta do painel (sem UI)."""

from src.consultas import (
    buscar_fornecedores,
    buscar_pessoas,
    metricas_gerais,
    ranking_atencao,
)
from src.db import init_db


def _seed(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.executemany(
        "INSERT INTO fornecedores (cnpj, nome, valor_pago) VALUES (?,?,?)",
        [
            ("09095412000127", "ABBC", 2264000.0),       # inapta + sancionada
            ("44782779000110", "SANTA CASA", 9876208.0),  # intervenção + concentração
            ("00000000000191", "EMPRESA LIMPA", 100.0),   # sem bandeira
        ],
    )
    conn.executemany(
        "INSERT INTO empresas (cnpj, razao_social, situacao_cadastral, situacao_especial) VALUES (?,?,?,?)",
        [
            ("09095412000127", "ABBC", "INAPTA", None),
            ("44782779000110", "SANTA CASA", "ATIVA", "INTERVENCAO"),
            ("00000000000191", "EMPRESA LIMPA", "ATIVA", None),
        ],
    )
    conn.execute(
        "INSERT INTO sancoes_encontradas (id, alvo_tipo, alvo_cnpj, fonte, categoria, vinculo) "
        "VALUES ('s','fornecedor','09095412000127','CEIS','Impedimento','cnpj')"
    )
    conn.execute(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio) VALUES ('x','09095412000127','HENRIQUE DUARTE PRATA')"
    )
    conn.commit()
    return conn


def test_metricas(tmp_path):
    conn = _seed(tmp_path)
    m = metricas_gerais(conn)
    assert m["fornecedores"] == 3
    assert m["empresas_enriquecidas"] == 3
    assert m["sancoes"] == 1
    assert m["total_pago"] > 0
    conn.close()


def test_ranking_ordena_por_atencao(tmp_path):
    conn = _seed(tmp_path)
    rank = ranking_atencao(conn, limite=10)
    # ABBC (situação + sanção) deve estar à frente; empresa limpa não entra.
    cnpjs = [r["cnpj"] for r in rank]
    assert "09095412000127" in cnpjs
    assert "44782779000110" in cnpjs
    assert "00000000000191" not in cnpjs
    # Ordenado desc por nível.
    niveis = [r["nivel_atencao"] for r in rank]
    assert niveis == sorted(niveis, reverse=True)
    # ABBC tem situação(4) + sanção(5) = 9.
    abbc = next(r for r in rank if r["cnpj"] == "09095412000127")
    assert abbc["nivel_atencao"] == 9
    conn.close()


def test_buscar_fornecedores(tmp_path):
    conn = _seed(tmp_path)
    assert buscar_fornecedores(conn, "SANTA")[0]["cnpj"] == "44782779000110"
    assert buscar_fornecedores(conn, "09095412")[0]["nome"] == "ABBC"
    assert buscar_fornecedores(conn, "") == []
    conn.close()


def test_buscar_pessoas(tmp_path):
    conn = _seed(tmp_path)
    res = buscar_pessoas(conn, "HENRIQUE")
    assert res and res[0]["cnpj_empresa"] == "09095412000127"
    conn.close()
