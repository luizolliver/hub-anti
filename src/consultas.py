"""
Consultas do painel — Etapa 10 (lógica separada da UI).

Toda a lógica de acesso a dados que alimenta o dashboard vive aqui, em funções
testáveis, sem nenhuma dependência do Streamlit. A UI (`app/dashboard.py`) só
chama estas funções e desenha o resultado.
"""

from __future__ import annotations

import sqlite3

import config
from src.analysis.flags import (
    concentracao_fornecedor,
    fornecedor_ou_socio_sancionado,
    situacao_cadastral_irregular,
)


def _total_pago(conn: sqlite3.Connection) -> float:
    return conn.execute("SELECT COALESCE(SUM(valor_pago), 0) FROM fornecedores").fetchone()[0]


def metricas_gerais(conn: sqlite3.Connection) -> dict:
    """Contadores para a visão geral do painel."""
    um = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "fornecedores": um("SELECT COUNT(*) FROM fornecedores"),
        "empresas_enriquecidas": um("SELECT COUNT(*) FROM empresas"),
        "contratos": um("SELECT COUNT(*) FROM contratos"),
        "despesas": um("SELECT COUNT(*) FROM despesas"),
        "total_pago": um("SELECT COALESCE(SUM(valor_pago),0) FROM fornecedores"),
        "sancoes": um("SELECT COUNT(*) FROM sancoes_encontradas"),
        "doacoes": um("SELECT COUNT(*) FROM doacoes_relacionadas"),
        "socios": um("SELECT COUNT(*) FROM socios"),
    }


def _bandeiras_lote(conn: sqlite3.Connection) -> dict[str, list]:
    """
    Calcula as bandeiras de TODOS os fornecedores de uma vez (sem N+1 queries),
    a partir de empresas (situação), sanções e concentração. Retorna
    {cnpj: [Bandeira, ...]}.
    """
    total = _total_pago(conn)
    empresas = {
        r["cnpj"]: r
        for r in conn.execute(
            "SELECT cnpj, situacao_cadastral, situacao_especial FROM empresas"
        )
    }
    sancoes: dict[str, list] = {}
    for r in conn.execute(
        "SELECT alvo_cnpj, fonte, categoria, nome_sancionado, vinculo FROM sancoes_encontradas"
    ):
        sancoes.setdefault(r["alvo_cnpj"], []).append(dict(r))

    resultado: dict[str, list] = {}
    for f in conn.execute("SELECT cnpj, valor_pago FROM fornecedores"):
        cnpj = f["cnpj"]
        bandeiras = []
        emp = empresas.get(cnpj)
        if emp:
            b = situacao_cadastral_irregular(emp["situacao_cadastral"], emp["situacao_especial"])
            if b:
                bandeiras.append(b)
        b = fornecedor_ou_socio_sancionado(sancoes.get(cnpj))
        if b:
            bandeiras.append(b)
        b = concentracao_fornecedor(f["valor_pago"], total, config.LIMIAR_CONCENTRACAO)
        if b:
            bandeiras.append(b)
        if bandeiras:
            resultado[cnpj] = bandeiras
    return resultado


def ranking_atencao(conn: sqlite3.Connection, limite: int = 50, minimo: int = 1) -> list[dict]:
    """
    Fornecedores ordenados por nível de atenção (soma dos pesos das bandeiras),
    do maior para o menor. Só inclui quem tem nível >= `minimo`.
    """
    bandeiras = _bandeiras_lote(conn)
    nomes = {
        r["cnpj"]: (r["nome"], r["valor_pago"])
        for r in conn.execute("SELECT cnpj, nome, valor_pago FROM fornecedores")
    }
    linhas = []
    for cnpj, bs in bandeiras.items():
        nivel = sum(b.peso for b in bs)
        if nivel < minimo:
            continue
        nome, valor = nomes.get(cnpj, (None, 0))
        linhas.append({
            "cnpj": cnpj,
            "nome": nome,
            "valor_pago": valor or 0,
            "nivel_atencao": nivel,
            "bandeiras": [b.codigo for b in bs],
        })
    linhas.sort(key=lambda x: (x["nivel_atencao"], x["valor_pago"]), reverse=True)
    return linhas[:limite]


def buscar_fornecedores(conn: sqlite3.Connection, termo: str, limite: int = 50) -> list[dict]:
    """Busca fornecedores por trecho do nome ou do CNPJ."""
    termo = (termo or "").strip()
    if not termo:
        return []
    like = f"%{termo}%"
    rows = conn.execute(
        "SELECT cnpj, nome, valor_pago, n_despesas FROM fornecedores "
        "WHERE nome LIKE ? OR cnpj LIKE ? ORDER BY valor_pago DESC LIMIT ?",
        (like, like, limite),
    ).fetchall()
    return [dict(r) for r in rows]


def buscar_pessoas(conn: sqlite3.Connection, termo: str, limite: int = 50) -> list[dict]:
    """Busca sócios por nome (casamento aproximado por trecho)."""
    termo = (termo or "").strip()
    if not termo:
        return []
    like = f"%{termo}%"
    rows = conn.execute(
        "SELECT DISTINCT nome_socio, cnpj_empresa, qualificacao, documento_visivel "
        "FROM socios WHERE nome_socio LIKE ? LIMIT ?",
        (like, limite),
    ).fetchall()
    return [dict(r) for r in rows]


def listar_contratos(conn: sqlite3.Connection, limite: int = 100) -> list[dict]:
    """Contratos do PNCP ordenados por valor (para a aba de contratos)."""
    rows = conn.execute(
        "SELECT id, orgao, modalidade, objeto, valor, data, fornecedor_nome "
        "FROM contratos ORDER BY valor DESC LIMIT ?",
        (limite,),
    ).fetchall()
    return [dict(r) for r in rows]
