"""
Consultas do painel — Etapa 10 (lógica separada da UI).

Toda a lógica de acesso a dados que alimenta o dashboard vive aqui, em funções
testáveis, sem nenhuma dependência do Streamlit. A UI (`app/dashboard.py`) só
chama estas funções e desenha o resultado.
"""

from __future__ import annotations

import datetime
import re
import sqlite3

from src.analysis.flags import avaliar_fornecedor
from src.normalize.entidades import cpf_nucleo


def _total_pago(conn: sqlite3.Connection) -> float:
    return conn.execute("SELECT COALESCE(SUM(valor_pago), 0) FROM fornecedores").fetchone()[0]


# ---------------------------------------------------------------------------
# Contexto de avaliação (fonte ÚNICA de verdade das bandeiras de fornecedor).
# Tanto o ranking quanto o dossiê montam este contexto e chamam
# `avaliar_fornecedor`, garantindo que perfil e ranking nunca divirjam.
# ---------------------------------------------------------------------------
def totais_orgao_ano(conn: sqlite3.Connection) -> dict:
    """{(orgao, ano): {'total': R$, 'n': qtde}} sobre todos os contratos."""
    out: dict[tuple, dict] = {}
    for r in conn.execute(
        "SELECT orgao, ano, COUNT(*) n, COALESCE(SUM(valor),0) total FROM contratos "
        "WHERE orgao IS NOT NULL AND ano IS NOT NULL GROUP BY orgao, ano"
    ):
        out[(r["orgao"], r["ano"])] = {"total": r["total"], "n": r["n"]}
    return out


def _mapa_irmas(conn: sqlite3.Connection) -> dict[str, set]:
    """
    {cnpj_fornecedor: set(cnpjs fornecedores que compartilham um mesmo sócio)}.

    "Mesmo sócio" = mesma chave (nome normalizado + 6 dígitos visíveis do CPF),
    a mesma noção de "mesma pessoa" usada na rede (Etapa 7). O conjunto inclui o
    próprio CNPJ. Só considera empresas que são fornecedoras do município.
    """
    forn = {r["cnpj"] for r in conn.execute("SELECT cnpj FROM fornecedores")}
    socio_chaves: dict[str, set] = {}   # cnpj_empresa -> {(nome_chave, visivel)}
    grupo_por_chave: dict[tuple, set] = {}  # (nome_chave, visivel) -> {cnpj_empresa}
    for r in conn.execute(
        "SELECT cnpj_empresa, nome_socio_chave, documento_visivel FROM socios "
        "WHERE documento_visivel IS NOT NULL AND tipo_socio = 'PF'"
    ):
        ce = r["cnpj_empresa"]
        if ce not in forn:
            continue
        chave = (r["nome_socio_chave"] or "", r["documento_visivel"])
        socio_chaves.setdefault(ce, set()).add(chave)
        grupo_por_chave.setdefault(chave, set()).add(ce)
    irmas: dict[str, set] = {}
    for ce, chaves in socio_chaves.items():
        grupo: set = set()
        for ch in chaves:
            grupo |= grupo_por_chave.get(ch, set())
        irmas[ce] = grupo  # inclui o próprio ce
    return irmas


def empresas_irmas(conn: sqlite3.Connection, cnpj: str) -> list[dict]:
    """
    Empresas "irmãs": outras fornecedoras que têm um sócio em comum com `cnpj`.
    Cada item: cnpj, nome, valor (pago + contratado) e o sócio que faz o elo.
    Ordenadas por valor recebido. (Bug 2.)
    """
    irmas = _mapa_irmas(conn)
    grupo = irmas.get(cnpj, set())
    outras = [c for c in grupo if c != cnpj]
    if not outras:
        return []
    info = {
        r["cnpj"]: r
        for r in conn.execute("SELECT cnpj, nome, valor_pago, valor_contratos FROM fornecedores")
    }
    # Sócios (chave) do próprio CNPJ, para nomear o elo.
    meus = {
        (r["nome_socio_chave"] or "", r["documento_visivel"]): r["nome_socio"]
        for r in conn.execute(
            "SELECT nome_socio, nome_socio_chave, documento_visivel FROM socios "
            "WHERE cnpj_empresa = ? AND documento_visivel IS NOT NULL AND tipo_socio='PF'",
            (cnpj,),
        )
    }
    res = []
    for c in outras:
        f = info.get(c)
        # acha um sócio em comum para rotular o elo
        elo = None
        for r in conn.execute(
            "SELECT nome_socio, nome_socio_chave, documento_visivel FROM socios "
            "WHERE cnpj_empresa = ? AND tipo_socio='PF'",
            (c,),
        ):
            ch = (r["nome_socio_chave"] or "", r["documento_visivel"])
            if ch in meus:
                elo = r["nome_socio"] or meus[ch]
                break
        valor = ((f["valor_pago"] or 0) + (f["valor_contratos"] or 0)) if f else 0
        res.append({
            "cnpj": c,
            "nome": f["nome"] if f else None,
            "valor": valor,
            "socio_comum": elo,
        })
    res.sort(key=lambda x: x["valor"], reverse=True)
    return res


def _ctx_base(conn: sqlite3.Connection) -> dict:
    """Partes do contexto que são iguais para todos os fornecedores (1x)."""
    return {
        "total_pago": _total_pago(conn),
        "totais_orgao_ano": totais_orgao_ano(conn),
    }


def contexto_fornecedores(conn: sqlite3.Connection) -> dict[str, dict]:
    """Monta, em lote, o contexto de avaliação de TODOS os fornecedores."""
    base = _ctx_base(conn)
    emp = {
        r["cnpj"]: r
        for r in conn.execute(
            "SELECT cnpj, situacao_cadastral, situacao_especial, natureza_juridica, "
            "data_inicio_atividade FROM empresas"
        )
    }
    sanc: dict[str, list] = {}
    for r in conn.execute(
        "SELECT alvo_cnpj, fonte, categoria, nome_sancionado, vinculo FROM sancoes_encontradas"
    ):
        sanc.setdefault(r["alvo_cnpj"], []).append(dict(r))
    contr: dict[str, list] = {}
    for r in conn.execute(
        "SELECT fornecedor_cnpj, data, modalidade, valor, objeto, orgao, ano FROM contratos "
        "WHERE fornecedor_cnpj IS NOT NULL"
    ):
        contr.setdefault(r["fornecedor_cnpj"], []).append(dict(r))
    irmas = _mapa_irmas(conn)

    out: dict[str, dict] = {}
    for f in conn.execute("SELECT cnpj, valor_pago FROM fornecedores"):
        c = f["cnpj"]
        e = emp.get(c)
        out[c] = {
            **base,
            "situacao_cadastral": e["situacao_cadastral"] if e else None,
            "situacao_especial": e["situacao_especial"] if e else None,
            "natureza_juridica": e["natureza_juridica"] if e else None,
            "data_inicio_atividade": e["data_inicio_atividade"] if e else None,
            "sancoes": sanc.get(c),
            "valor_pago": f["valor_pago"],
            "contratos": contr.get(c, []),
            "n_empresas_irmas_fornecedoras": len(irmas.get(c) or ()),
        }
    return out


def contexto_de(conn: sqlite3.Connection, cnpj: str) -> dict:
    """Contexto de avaliação de UM fornecedor (usado pelo dossiê)."""
    e = conn.execute(
        "SELECT situacao_cadastral, situacao_especial, natureza_juridica, "
        "data_inicio_atividade FROM empresas WHERE cnpj = ?",
        (cnpj,),
    ).fetchone()
    sanc = [
        dict(r) for r in conn.execute(
            "SELECT fonte, categoria, nome_sancionado, vinculo FROM sancoes_encontradas "
            "WHERE alvo_cnpj = ?",
            (cnpj,),
        )
    ]
    contratos = [
        dict(r) for r in conn.execute(
            "SELECT data, modalidade, valor, objeto, orgao, ano FROM contratos "
            "WHERE fornecedor_cnpj = ?",
            (cnpj,),
        )
    ]
    f = conn.execute("SELECT valor_pago FROM fornecedores WHERE cnpj = ?", (cnpj,)).fetchone()
    irmas = empresas_irmas(conn, cnpj)
    return {
        **_ctx_base(conn),
        "situacao_cadastral": e["situacao_cadastral"] if e else None,
        "situacao_especial": e["situacao_especial"] if e else None,
        "natureza_juridica": e["natureza_juridica"] if e else None,
        "data_inicio_atividade": e["data_inicio_atividade"] if e else None,
        "sancoes": sanc or None,
        "valor_pago": f["valor_pago"] if f else None,
        "contratos": contratos,
        "n_empresas_irmas_fornecedoras": (len(irmas) + 1) if irmas else 0,
    }


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
    pela fonte única `avaliar_fornecedor`. Retorna {cnpj: [Bandeira, ...]}.
    """
    resultado: dict[str, list] = {}
    for cnpj, ctx in contexto_fornecedores(conn).items():
        bandeiras = avaliar_fornecedor(ctx)["bandeiras"]
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


def buscar_socios(conn: sqlite3.Connection, termo: str, limite: int = 50) -> list[dict]:
    """
    Busca por sócio (nome OU CPF) e devolve, por pessoa, TODAS as empresas
    fornecedoras onde ela é sócia, com o valor total recebido. (Parte 4.2.)

    O CPF pode ser digitado completo ou parcial; reduzimos ao núcleo de 6 dígitos
    (mesma técnica das outras etapas) para casar com o CPF mascarado do QSA.
    """
    termo = (termo or "").strip()
    if not termo:
        return []
    digitos = re.sub(r"\D", "", termo)
    nucleo = cpf_nucleo(digitos) if len(digitos) in (6, 11) else None
    rows = conn.execute(
        "SELECT nome_socio, nome_socio_chave, documento_visivel, cnpj_empresa "
        "FROM socios WHERE tipo_socio='PF' AND (nome_socio LIKE ? "
        "OR (? IS NOT NULL AND documento_visivel = ?))",
        (f"%{termo}%", nucleo, nucleo),
    ).fetchall()
    info = {
        r["cnpj"]: r
        for r in conn.execute("SELECT cnpj, nome, valor_pago, valor_contratos FROM fornecedores")
    }
    pessoas: dict[tuple, dict] = {}
    for r in rows:
        if r["cnpj_empresa"] not in info:
            continue  # só empresas fornecedoras
        chave = (r["nome_socio_chave"] or "", r["documento_visivel"])
        p = pessoas.setdefault(chave, {
            "nome": r["nome_socio"], "documento_visivel": r["documento_visivel"],
            "empresas": {}, "total": 0.0,
        })
        f = info[r["cnpj_empresa"]]
        valor = (f["valor_pago"] or 0) + (f["valor_contratos"] or 0)
        if r["cnpj_empresa"] not in p["empresas"]:
            p["empresas"][r["cnpj_empresa"]] = {"cnpj": r["cnpj_empresa"], "nome": f["nome"], "valor": valor}
            p["total"] += valor
    saida = []
    for p in pessoas.values():
        p["empresas"] = sorted(p["empresas"].values(), key=lambda x: x["valor"], reverse=True)
        saida.append(p)
    saida.sort(key=lambda x: (len(x["empresas"]), x["total"]), reverse=True)
    return saida[:limite]


def buscar_por_objeto(conn: sqlite3.Connection, termo: str, limite: int = 100) -> list[dict]:
    """Busca contratos cujo objeto contém o termo (ex.: 'pavimentação'). Parte 4.1."""
    termo = (termo or "").strip()
    if not termo:
        return []
    rows = conn.execute(
        "SELECT id, fonte, data, orgao, modalidade, objeto, valor, fornecedor_nome, fornecedor_cnpj "
        "FROM contratos WHERE objeto LIKE ? ORDER BY valor DESC LIMIT ?",
        (f"%{termo}%", limite),
    ).fetchall()
    return [dict(r) for r in rows]


def modalidades(conn: sqlite3.Connection) -> list[str]:
    """Modalidades distintas presentes em contratos (para o filtro da UI)."""
    return [
        r[0] for r in conn.execute(
            "SELECT DISTINCT modalidade FROM contratos WHERE modalidade IS NOT NULL ORDER BY modalidade"
        )
    ]


def orgaos(conn: sqlite3.Connection) -> list[str]:
    """Órgãos distintos presentes em contratos (para o filtro da UI)."""
    return [
        r[0] for r in conn.execute(
            "SELECT DISTINCT orgao FROM contratos WHERE orgao IS NOT NULL ORDER BY orgao"
        )
    ]


def listar_contratos(
    conn: sqlite3.Connection,
    limite: int = 200,
    modalidade: str | None = None,
    orgao: str | None = None,
    valor_min: float | None = None,
    valor_max: float | None = None,
    data_ini: str | None = None,
    data_fim: str | None = None,
) -> list[dict]:
    """Contratos com filtros opcionais (modalidade, órgão, faixa de valor, período)."""
    where: list[str] = []
    params: list = []
    filtros = [
        ("modalidade = ?", modalidade),
        ("orgao = ?", orgao),
        ("valor >= ?", valor_min),
        ("valor <= ?", valor_max),
        ("data >= ?", data_ini),
        ("data <= ?", data_fim),
    ]
    for clausula, valor in filtros:
        if valor is not None and valor != "":
            where.append(clausula)
            params.append(valor)
    sql = (
        "SELECT id, fonte, orgao, modalidade, objeto, valor, data, ano, "
        "fornecedor_nome, fornecedor_cnpj, id_origem FROM contratos"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY data DESC, valor DESC LIMIT ?"
    params.append(limite)
    return [dict(r) for r in conn.execute(sql, params)]


def contratos_do_fornecedor(conn: sqlite3.Connection, cnpj: str) -> list[dict]:
    """Contratos individuais de um fornecedor (para o perfil e o dossiê). Parte 3.1."""
    rows = conn.execute(
        "SELECT id, fonte, orgao, modalidade, objeto, valor, data, ano, id_origem "
        "FROM contratos WHERE fornecedor_cnpj = ? ORDER BY data DESC, valor DESC",
        (cnpj,),
    ).fetchall()
    return [dict(r) for r in rows]


def valor_por_ano(conn: sqlite3.Connection, cnpj: str) -> dict[str, float]:
    """
    Valor contratado por ano (contratos do TCE-SP/PNCP) de um fornecedor —
    base do gráfico temporal do perfil (revela picos eleitorais). Parte 3.2.
    """
    out: dict[str, float] = {}
    for r in conn.execute(
        "SELECT ano, COALESCE(SUM(valor),0) v FROM contratos "
        "WHERE fornecedor_cnpj = ? AND ano IS NOT NULL GROUP BY ano ORDER BY ano",
        (cnpj,),
    ):
        out[r["ano"]] = round(r["v"], 2)
    return out


def alertas_recentes(conn: sqlite3.Connection, dias: int = 90, limite: int = 50) -> list[dict]:
    """
    Contratos assinados nos últimos `dias` cujo fornecedor já tem ao menos uma
    bandeira ativa — transforma o hub em monitor. Parte 5.
    """
    bandeiras = _bandeiras_lote(conn)
    corte = (datetime.date.today() - datetime.timedelta(days=dias)).isoformat()
    saida = []
    for r in conn.execute(
        "SELECT data, orgao, valor, fornecedor_cnpj, fornecedor_nome FROM contratos "
        "WHERE data >= ? AND fornecedor_cnpj IS NOT NULL ORDER BY data DESC",
        (corte,),
    ):
        bs = bandeiras.get(r["fornecedor_cnpj"])
        if not bs:
            continue
        saida.append({
            "data": r["data"],
            "fornecedor": r["fornecedor_nome"],
            "cnpj": r["fornecedor_cnpj"],
            "orgao": r["orgao"],
            "valor": r["valor"],
            "bandeiras": [b.codigo for b in bs],
        })
        if len(saida) >= limite:
            break
    return saida
