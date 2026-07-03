"""
Interface web do Observatório (FastAPI + Jinja + HTMX).

Roda em PARALELO ao painel Streamlit — não substitui nada ainda. Esta primeira
entrega serve APENAS a tela de ranking, ponta a ponta, com dados reais do SQLite.

Princípio: a camada de dados (`src/consultas.py`) é pura e testada; aqui só a
consumimos. Nada de regra de negócio nesta camada — só transporte e apresentação.

Rodar:  uvicorn web.app:app --reload --port 8000
        (o Streamlit segue em 8501, para comparação lado a lado.)
"""

from __future__ import annotations

import json
import sqlite3
from functools import lru_cache
from pathlib import Path

from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

import config
from src import consultas
from src.reports import dossie as dossie_mod
from web import sources
from web.flags_meta import FLAGS_META

BASE = Path(__file__).resolve().parent
app = FastAPI(title="Observatório Barretos — web", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _filtros(modalidade, orgao, valor_min, data_ini, data_fim) -> dict | None:
    """Monta o dict de filtros no formato que `consultas` espera (ou None)."""
    f = {
        "modalidade": modalidade or None,
        "orgao": orgao or None,
        "valor_min": valor_min or 0,
        "data_ini": data_ini or None,
        "data_fim": data_fim or None,
    }
    return f


@lru_cache(maxsize=128)
def _ranking_cached(
    minimo: int,
    limite: int,
    modalidade: str,
    orgao: str,
    valor_min: float,
    data_ini: str,
    data_fim: str,
) -> list[dict]:
    """
    Cache do ranking por combinação de filtros (args imutáveis → hasháveis).
    Recalcular a cada request seria caro; o botão de recarregar limpa o cache.
    """
    conn = _conn()
    try:
        return consultas.ranking_atencao(
            conn,
            limite=limite,
            minimo=minimo,
            filtros=_filtros(modalidade, orgao, valor_min, data_ini, data_fim),
        )
    finally:
        conn.close()


def _to_supplier(r: dict) -> dict:
    """Adapta o dict do ranking real ao contrato que o front (v3) consome."""
    return {
        "lvl": r["nivel_atencao"],
        "cnpj": r["cnpj"],
        "name": r["nome"] or "—",
        "paid": r["valor_total"],   # R$ movimentado (pago + contratado)
        "flags": r["bandeiras"],
    }


@app.get("/")
def index(request: Request):
    conn = _conn()
    try:
        modalidades = consultas.modalidades(conn)
        orgaos = consultas.orgaos(conn)
    finally:
        conn.close()
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "modalidades": modalidades,
            "orgaos": orgaos,
            "flags_meta_json": json.dumps(FLAGS_META, ensure_ascii=False),
        },
    )


@app.get("/api/ranking")
def api_ranking(
    minimo: int = Query(1, ge=1),
    limite: int = Query(50, ge=1, le=200),
    modalidade: str = "",
    orgao: str = "",
    valor_min: float = 0,
    data_ini: str = "",
    data_fim: str = "",
):
    rank = _ranking_cached(minimo, limite, modalidade, orgao, valor_min, data_ini, data_fim)
    filtro_ativo = any([modalidade, orgao, valor_min, data_ini, data_fim])
    return JSONResponse(
        {
            "count": len(rank),
            "minimo": minimo,
            "filtro_ativo": filtro_ativo,
            "suppliers": [_to_supplier(r) for r in rank],
            "flags_meta": FLAGS_META,
        }
    )


@lru_cache(maxsize=1)
def _niveis_cached() -> dict[str, dict]:
    """
    Mapa {cnpj: {"lvl", "flags"}} de todos os fornecedores COM bandeira — usado
    pela busca para exibir o nível sem recalcular por resultado. Quem não está no
    mapa tem nível 0 (nenhuma bandeira).
    """
    conn = _conn()
    try:
        rank = consultas.ranking_atencao(conn, limite=1_000_000, minimo=1)
    finally:
        conn.close()
    return {r["cnpj"]: {"lvl": r["nivel_atencao"], "flags": r["bandeiras"]} for r in rank}


@app.get("/api/metricas")
def api_metricas():
    conn = _conn()
    try:
        m = consultas.metricas_gerais(conn)
    finally:
        conn.close()
    return {
        "stats": [
            {"label": "Fornecedores", "val": m["fornecedores"], "src": "TCE-SP"},
            {"label": "Empresas (QSA)", "val": m["empresas_enriquecidas"], "src": "Receita"},
            {"label": "R$ pago", "val": round(m["total_pago"] / 1e9, 2),
             "prefix": "R$ ", "suffix": " bi", "dec": 2, "src": "TCE-SP"},
            {"label": "Contratos", "val": m["contratos"], "src": "PNCP"},
            {"label": "Despesas", "val": m["despesas"], "src": "TCE-SP"},
            {"label": "Sócios", "val": m["socios"], "src": "Receita/QSA"},
            {"label": "Sanções cruzadas", "val": m["sancoes"], "alert": True, "src": "CEIS/CNEP"},
            {"label": "Doações ligadas", "val": m["doacoes"], "src": "TSE"},
        ]
    }


@app.get("/api/busca")
def api_busca(q: str = ""):
    """Busca unificada: fornecedores (nome/CNPJ) + pessoas (sócio por nome/CPF)."""
    q = (q or "").strip()
    if not q:
        return {"fornecedores": [], "pessoas": []}
    conn = _conn()
    try:
        forns = consultas.buscar_fornecedores(conn, q, limite=20)
        pessoas = consultas.buscar_socios(conn, q, limite=8)
    finally:
        conn.close()
    niveis = _niveis_cached()

    def _forn(f: dict) -> dict:
        n = niveis.get(f["cnpj"], {})
        return {
            "cnpj": f["cnpj"],
            "name": f["nome"] or "—",
            "lvl": n.get("lvl", 0),
            "flags": n.get("flags", []),
        }

    return {
        "fornecedores": [_forn(f) for f in forns],
        "pessoas": [
            {
                "nome": p["nome"],
                "documento": p.get("documento_visivel"),
                "empresas": [
                    {"cnpj": e["cnpj"], "name": e["nome"], "valor": e["valor"]}
                    for e in p["empresas"]
                ],
            }
            for p in pessoas
        ],
    }


@app.get("/api/contratos")
def api_contratos(
    modalidade: str = "",
    orgao: str = "",
    valor_min: float = 0,
    data_ini: str = "",
    data_fim: str = "",
    limite: int = Query(200, ge=1, le=500),
):
    conn = _conn()
    try:
        rows = consultas.listar_contratos(
            conn,
            limite=limite,
            modalidade=modalidade or None,
            orgao=orgao or None,
            valor_min=valor_min or None,
            data_ini=data_ini or None,
            data_fim=data_fim or None,
        )
    finally:
        conn.close()
    return {
        "count": len(rows),
        "limite": limite,
        "contratos": [
            {
                "data": c["data"],
                "orgao": c["orgao"],
                "modalidade": c["modalidade"],
                "valor": c["valor"],
                "objeto": c["objeto"],
                "fornecedor": c["fornecedor_nome"],
                "cnpj": c["fornecedor_cnpj"],
                "fonte": c["fonte"],
                "link": sources.contrato_link(c["fonte"], c["id_origem"]),
            }
            for c in rows
        ],
    }


@app.get("/api/perfil/{cnpj}")
def api_perfil(cnpj: str):
    """Perfil do fornecedor a partir do dossiê (mesma fonte do relatório)."""
    conn = _conn()
    try:
        d = dossie_mod.montar_dossie(conn, cnpj)
    finally:
        conn.close()
    emp = d.get("empresa") or {}
    forn = d.get("fornecedor") or {}
    nome = emp.get("razao_social") or forn.get("nome") or cnpj
    bandeiras = d.get("bandeiras") or []
    contratos = d.get("contratos") or []
    return {
        "cnpj": cnpj,
        "name": nome,
        "lvl": d.get("nivel_atencao", 0),
        "flags": [b.codigo for b in bandeiras],
        "flags_detail": [
            {"code": b.codigo, "desc": b.descricao, "peso": b.peso} for b in bandeiras
        ],
        "cad": {
            "situacao": emp.get("situacao_cadastral") or "—",
            "especial": emp.get("situacao_especial"),
            "abertura": emp.get("data_inicio_atividade") or "—",
            "natureza": emp.get("natureza_juridica") or "—",
            "porte": emp.get("porte") or "—",
            "cidade": f"{emp.get('municipio') or '—'}/{emp.get('uf') or '—'}",
        },
        "money": [[r["evento"], r["soma"]] for r in d.get("despesas_por_evento") or []],
        "valor_por_ano": d.get("valor_por_ano") or {},
        "n_contratos": len(contratos),
        "contratos": [
            {
                "data": c.get("data"),
                "orgao": c.get("orgao"),
                "modalidade": c.get("modalidade"),
                "valor": c.get("valor"),
                "objeto": c.get("objeto"),
                "fonte": c.get("fonte"),
                "link": sources.contrato_link(c.get("fonte"), c.get("id_origem")),
            }
            for c in contratos[:50]
        ],
        "socios": [
            {"nome": s.get("nome_socio"), "qualificacao": s.get("qualificacao"),
             "tipo": s.get("tipo_socio")}
            for s in d.get("socios") or []
        ],
        "sancoes": [
            {
                "fonte": s.get("fonte"),
                "categoria": s.get("categoria"),
                "vinculo": s.get("vinculo"),
                # vínculo "cnpj" → sanção é do próprio CNPJ perfilado; senão,
                # busca pelo nome do sancionado (sócio/homônimo a apurar).
                "link": sources.sancao_link(
                    s.get("fonte"),
                    documento=cnpj if s.get("vinculo") == "cnpj" else None,
                    nome=s.get("nome_sancionado"),
                ),
            }
            for s in d.get("sancoes") or []
        ],
        "irmas": [
            {"cnpj": p.get("cnpj"), "nome": p.get("nome"),
             "valor": p.get("valor"), "socio": p.get("socio_comum")}
            for p in d.get("irmas") or []
        ],
    }


@app.get("/dossie/{cnpj}", response_class=HTMLResponse)
def dossie_completo(cnpj: str):
    """Dossiê completo em HTML, gerado sob demanda (mesma fonte do relatório .md/.pdf)."""
    conn = _conn()
    try:
        dados = dossie_mod.montar_dossie(conn, cnpj)
    finally:
        conn.close()
    md = dossie_mod.gerar_markdown(dados)
    return HTMLResponse(dossie_mod.gerar_html(md, titulo=f"Dossiê {cnpj}"))


@app.post("/api/recarregar")
def recarregar():
    """Limpa os caches derivados (equivalente ao botão de recarregar do Streamlit)."""
    _ranking_cached.cache_clear()
    _niveis_cached.cache_clear()
    return {"ok": True}
