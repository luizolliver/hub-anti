"""
Painel do Observatório — Etapa 10 (Streamlit, dark developer dashboard).

Interface estilo ferramenta de dev (Vercel/Railway/Chutes): fundo quase preto,
cartões com borda fina, JetBrains Mono, acentos de cor só em indicadores de
status. Navega pelos fornecedores de Barretos, seu nível de atenção, perfil
completo, rede e exportação de dossiê.

Toda a lógica de dados está em `src/consultas.py` e `src/reports/dossie.py`
(testadas). Este arquivo é só apresentação.

Rodar:
    streamlit run app/dashboard.py
"""

from __future__ import annotations

# Entry-point: o `streamlit run` coloca a pasta app/ no sys.path, não a raiz do
# projeto. Inserimos a raiz aqui para que `import config` e `from src...` achem
# os módulos, independentemente de onde o comando é chamado.
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import sqlite3  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from src import consultas  # noqa: E402
from src.reports.dossie import gerar_html, gerar_markdown, montar_dossie  # noqa: E402

st.set_page_config(page_title="OBSERVATÓRIO // BARRETOS", page_icon="▣", layout="wide")

# --- CSS: dark developer dashboard ------------------------------------------
# Estética de ferramenta de dev (estilo Vercel/Railway/Chutes): fundo quase
# preto, cartões #141414 com borda fina, JetBrains Mono, cantos ~3-4px, sem
# sombras nem gradientes, cores de acento só em indicadores de status.
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600&display=swap');

    :root {
        --bg:#0e0e0e; --card:#141414; --border:#1f1f1f;
        --text:#e8e8e8; --muted:#555555; --body:#888888;
        --green:#22c55e; --blue:#3b82f6; --yellow:#eab308; --red:#ef4444;
    }

    html, body, [class*="css"], .stApp, .stMarkdown,
    p, span, div, label, input, td, th, button, [data-baseweb] {
        font-family: 'JetBrains Mono', monospace !important;
    }
    .stApp { background: var(--bg); color: var(--text); }

    /* Tira o cromo do Streamlit (menu/rodapé/header) */
    #MainMenu, footer, header[data-testid="stHeader"] { visibility: hidden; height: 0; }

    /* Largura cheia, layout denso */
    .block-container { max-width: 100% !important; padding: 1.1rem 2rem 2.5rem !important; }

    /* Títulos */
    h1, h2, h3, h4 { color: var(--text) !important; font-weight: 500 !important;
        letter-spacing: .02em; margin-bottom:.4rem; }
    .stMarkdown p, .stMarkdown li { color: var(--body); font-size: 13px; }
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] * {
        color: var(--muted) !important; font-size: 12px; }

    /* Cartões de métrica */
    [data-testid="stMetric"] {
        background: var(--card); border: 1px solid var(--border);
        border-radius: 4px; padding: 20px; box-shadow: none;
    }
    [data-testid="stMetricLabel"], [data-testid="stMetricLabel"] * {
        text-transform: uppercase; letter-spacing: .1em;
        font-size: 11px !important; color: var(--muted) !important;
    }
    [data-testid="stMetricValue"] {
        font-size: 28px !important; font-weight: 500; color: var(--text) !important;
    }

    /* Botões: contorno fino, texto em caixa alta, hover clareia */
    .stButton > button, .stDownloadButton > button {
        background: transparent !important; border: 1px solid #2a2a2a !important;
        color: #aaaaaa !important; border-radius: 3px !important;
        text-transform: uppercase; font-size: 11px; letter-spacing: .08em;
        box-shadow: none !important;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        border-color: #444444 !important; color: #ffffff !important; background: transparent !important;
    }

    /* Barra lateral */
    section[data-testid="stSidebar"] { background: #0a0a0a; border-right: 1px solid #1a1a1a; }
    section[data-testid="stSidebar"] * { color: var(--body); }
    section[data-testid="stSidebar"] [role="radiogroup"] label { border-radius: 3px; padding:2px 4px; }

    /* Entradas, selects, sliders */
    .stTextInput input, .stNumberInput input,
    [data-baseweb="input"], [data-baseweb="select"] > div {
        background: #111111 !important; border: 1px solid #222222 !important;
        color: var(--text) !important; border-radius: 3px !important; box-shadow: none !important;
    }
    [data-testid="stSlider"] [role="slider"] { background: var(--blue) !important; }

    /* Tabela */
    [data-testid="stDataFrame"], .stDataFrame {
        border: 1px solid var(--border); border-radius: 4px; }

    a, a:visited { color: var(--blue) !important; }

    /* Componentes próprios */
    .dev-header {
        display:flex; align-items:center; justify-content:space-between;
        border:1px solid var(--border); background:var(--card);
        padding:14px 18px; border-radius:4px; margin-bottom:1.2rem;
    }
    .dev-header .title { color:var(--text); font-size:15px; font-weight:600; letter-spacing:.04em; }
    .dev-header .sub { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.1em; }
    .badge {
        display:inline-block; border:1px solid #2a2a2a; border-radius:3px;
        padding:2px 7px; margin:2px; font-size:11px; color:#aaaaaa;
        text-transform:uppercase; letter-spacing:.05em;
    }
    .alert {
        border:1px solid var(--border); border-left:3px solid var(--red);
        background:#141414; color:#e0a3a3; padding:8px 12px; margin:4px 0;
        font-size:13px; border-radius:3px;
    }
    /* Indicadores de status: quadradinhos 4x4 (sem bolinhas coloridas) */
    .sq { display:inline-block; width:4px; height:4px; vertical-align:middle; margin-right:6px; }
    .sq-green{background:var(--green);} .sq-blue{background:var(--blue);}
    .sq-yellow{background:var(--yellow);} .sq-red{background:var(--red);} .sq-muted{background:var(--muted);}
    .ok { color: var(--green); }
    .mono-dim { color: var(--muted); font-size:12px; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _sq(nivel) -> str:
    """Quadradinho 4x4 de status conforme o nível de atenção."""
    try:
        n = int(nivel)
    except (TypeError, ValueError):
        n = 0
    cor = "green" if n < 3 else "yellow" if n < 6 else "red"
    return f"<span class='sq sq-{cor}'></span>"


@st.cache_resource
def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _moeda(v) -> str:
    try:
        return f"R$ {float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _badges(codigos) -> str:
    return " ".join(f"<span class='badge'>{c}</span>" for c in codigos)


def _link_pncp(c: dict) -> str | None:
    """URL pública do contrato no PNCP, quando a fonte é PNCP."""
    if (c.get("fonte") or "") != "PNCP" or not c.get("id_origem"):
        return None
    partes = str(c["id_origem"]).strip("/").split("/")
    # espera ['contratos', CNPJ, ANO, SEQ]
    if len(partes) >= 4 and partes[0] == "contratos":
        return f"https://pncp.gov.br/app/contratos/{partes[1]}/{partes[2]}/{partes[3]}"
    return "https://pncp.gov.br"


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
def pagina_visao_geral(conn):
    st.subheader("▣ visão geral")
    m = consultas.metricas_gerais(conn)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("fornecedores", f"{m['fornecedores']:,}")
    c2.metric("empresas (QSA)", f"{m['empresas_enriquecidas']:,}")
    c3.metric("R$ pago (TCE)", _moeda(m["total_pago"]))
    c4.metric("contratos", f"{m['contratos']:,}")
    c5, c6, c7, c8 = st.columns(4)
    c5.metric("despesas", f"{m['despesas']:,}")
    c6.metric("sócios", f"{m['socios']:,}")
    c7.metric("sanções cruzadas", f"{m['sancoes']:,}")
    c8.metric("doações ligadas", f"{m['doacoes']:,}")

    st.markdown("#### topo do ranking de atenção")
    rank = consultas.ranking_atencao(conn, limite=10)
    if rank:
        st.dataframe(
            [{"nível": r["nivel_atencao"], "cnpj": r["cnpj"], "fornecedor": r["nome"],
              "R$ recebido": _moeda(r["valor_pago"]), "bandeiras": ", ".join(r["bandeiras"])} for r in rank],
            width="stretch", hide_index=True,
        )
    else:
        st.info("sem bandeiras ainda — rode os coletores e o enriquecimento (Etapas 4/5).")

    # Painel de monitor: contratos recentes que já têm bandeira (Parte 5).
    st.markdown("#### ⚠ alertas recentes (últimos 90 dias)")
    alertas = consultas.alertas_recentes(conn, dias=90)
    if alertas:
        st.caption(f"{len(alertas)} contrato(s) recente(s) com fornecedor já sinalizado.")
        st.dataframe(
            [{"data": a["data"], "fornecedor": a["fornecedor"], "órgão": a["orgao"],
              "valor": _moeda(a["valor"]), "bandeiras": ", ".join(a["bandeiras"])} for a in alertas],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("nenhum contrato assinado nos últimos 90 dias com bandeira ativa.")


def pagina_ranking(conn):
    st.subheader("▣ ranking de atenção")
    minimo = st.slider("nível mínimo de atenção", 1, 15, 1)
    limite = st.slider("quantos exibir", 10, 200, 50, step=10)
    rank = consultas.ranking_atencao(conn, limite=limite, minimo=minimo)
    st.caption(f"{len(rank)} fornecedores com nível ≥ {minimo}")
    for r in rank:
        cols = st.columns([1, 5, 3, 2])
        cols[0].markdown(
            f"{_sq(r['nivel_atencao'])}<span style='font-size:22px;font-weight:500'>"
            f"{r['nivel_atencao']}</span>",
            unsafe_allow_html=True,
        )
        cols[1].markdown(f"**{r['nome'] or '—'}**  \n`{r['cnpj']}`")
        cols[2].markdown(_badges(r["bandeiras"]), unsafe_allow_html=True)
        if cols[3].button("perfil ▸", key=f"go_{r['cnpj']}"):
            st.session_state["cnpj"] = r["cnpj"]
            st.session_state["nav"] = "perfil"
            st.rerun()


def pagina_buscar(conn):
    st.subheader("▣ buscar")
    modo = st.radio(
        "modo de busca", ["fornecedor", "objeto de contrato", "sócio (CPF ou nome)"],
        horizontal=True,
    )
    termo = st.text_input("termo", placeholder="> digite e tecle enter")
    if not termo:
        return

    if modo == "fornecedor":
        fns = consultas.buscar_fornecedores(conn, termo)
        if not fns:
            st.warning("nenhum fornecedor encontrado.")
        for f in fns:
            cols = st.columns([6, 3, 2])
            cols[0].markdown(f"**{f['nome'] or '—'}**  \n`{f['cnpj']}`")
            cols[1].markdown(f"recebido: {_moeda(f['valor_pago'])}")
            if cols[2].button("perfil ▸", key=f"b_{f['cnpj']}"):
                st.session_state["cnpj"] = f["cnpj"]
                st.session_state["nav"] = "perfil"
                st.rerun()

    elif modo == "objeto de contrato":
        contratos = consultas.buscar_por_objeto(conn, termo)
        if not contratos:
            st.warning("nenhum contrato com esse objeto.")
        else:
            st.caption(f"{len(contratos)} contrato(s) com objeto contendo “{termo}”.")
            st.dataframe(
                [{"data": c["data"], "órgão": c["orgao"], "modalidade": c["modalidade"],
                  "valor": _moeda(c["valor"]), "fornecedor": c["fornecedor_nome"],
                  "objeto": (c["objeto"] or "")[:90]} for c in contratos],
                width="stretch", hide_index=True,
            )

    else:  # sócio
        pessoas = consultas.buscar_socios(conn, termo)
        if not pessoas:
            st.warning("nenhum sócio encontrado entre as empresas fornecedoras.")
        for p in pessoas:
            cpf = p.get("documento_visivel")
            st.markdown(
                f"**{p['nome'] or '—'}**  ·  cpf parcial: `{cpf or '—'}`  ·  "
                f"{len(p['empresas'])} empresa(s) · total {_moeda(p['total'])}"
            )
            for e in p["empresas"]:
                cols = st.columns([6, 3, 2])
                cols[0].markdown(f"&nbsp;&nbsp;↳ {e['nome'] or '—'}  \n&nbsp;&nbsp;`{e['cnpj']}`",
                                 unsafe_allow_html=True)
                cols[1].markdown(_moeda(e["valor"]))
                if cols[2].button("perfil ▸", key=f"s_{p.get('documento_visivel')}_{e['cnpj']}"):
                    st.session_state["cnpj"] = e["cnpj"]
                    st.session_state["nav"] = "perfil"
                    st.rerun()


def pagina_perfil(conn):
    st.subheader("▣ perfil do fornecedor")
    cnpj = st.text_input("CNPJ", value=st.session_state.get("cnpj", ""))
    if not cnpj:
        st.info("informe um CNPJ ou venha do ranking/busca.")
        return
    dados = montar_dossie(conn, cnpj)
    emp = dados.get("empresa") or {}
    forn = dados.get("fornecedor") or {}
    nome = emp.get("razao_social") or forn.get("nome") or cnpj

    st.markdown(f"## {nome}")
    st.markdown(
        f"`{cnpj}`  ·  {_sq(dados['nivel_atencao'])}"
        f"nível de atenção: **{dados['nivel_atencao']}**",
        unsafe_allow_html=True,
    )

    # Bandeiras como alertas.
    if dados["bandeiras"]:
        for b in dados["bandeiras"]:
            st.markdown(f"<div class='alert'>⚑ <b>{b.codigo}</b> — {b.descricao}</div>",
                        unsafe_allow_html=True)
    else:
        st.markdown("<span class='ok'>nenhuma bandeira disparada.</span>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("#### cadastro (Receita)")
        if emp:
            st.write({
                "situação": emp.get("situacao_cadastral"),
                "especial": emp.get("situacao_especial"),
                "abertura": emp.get("data_inicio_atividade"),
                "natureza": emp.get("natureza_juridica"),
                "porte": emp.get("porte"),
                "município/UF": f"{emp.get('municipio')}/{emp.get('uf')}",
            })
        else:
            st.caption("não enriquecido (Etapa 4).")
        st.markdown("#### sócios (QSA)")
        if dados["socios"]:
            for s in dados["socios"]:
                st.write(f"- {s['nome_socio']} — {s.get('qualificacao') or '—'} ({s.get('tipo_socio')})")
        else:
            st.caption("sem QSA.")
    with col2:
        st.markdown("#### dinheiro recebido (TCE)")
        if dados["despesas_por_evento"]:
            st.dataframe(
                [{"evento": r["evento"], "linhas": r["n"], "valor": _moeda(r["soma"])}
                 for r in dados["despesas_por_evento"]],
                width="stretch", hide_index=True,
            )
        else:
            st.caption("sem despesas.")
        # Série temporal: valor contratado por ano (revela picos eleitorais).
        va = dados.get("valor_por_ano") or {}
        if va:
            st.markdown("#### valor contratado por ano")
            st.bar_chart(pd.DataFrame({"valor": list(va.values())}, index=list(va.keys())))
        st.markdown("#### rede societária (empresas irmãs)")
        irmas = dados.get("irmas") or []
        if irmas:
            st.dataframe(
                [{"empresa": p["nome"], "cnpj": p["cnpj"], "R$ recebido": _moeda(p["valor"]),
                  "sócio em comum": p["socio_comum"]} for p in irmas],
                width="stretch", hide_index=True,
            )
        else:
            st.caption("sem empresas irmãs (nenhum sócio em comum).")

    # Contratos individuais (Parte 3.1).
    st.markdown("#### contratos individuais")
    cs = dados.get("contratos") or []
    if cs:
        st.caption(f"{len(cs)} contrato(s).")
        st.dataframe(
            [{"data": c["data"], "órgão": c["orgao"], "modalidade": c["modalidade"],
              "valor": _moeda(c["valor"]), "objeto": (c["objeto"] or "")[:80],
              "fonte": c["fonte"], "PNCP": _link_pncp(c) or ""} for c in cs],
            width="stretch", hide_index=True,
            column_config={"PNCP": st.column_config.LinkColumn("PNCP", display_text="abrir")},
        )
    else:
        st.caption("sem contratos vinculados a este CNPJ.")

    st.markdown("#### sanções")
    if dados["sancoes"]:
        st.dataframe(
            [{"fonte": s["fonte"], "categoria": s["categoria"],
              "nome sancionado": s.get("nome_sancionado"), "vínculo": s["vinculo"]}
             for s in dados["sancoes"]],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("sem sanções cruzadas.")

    st.markdown("#### doações relacionadas (TSE)")
    if dados["doacoes"]:
        st.dataframe(
            [{"doador": d["doador_nome"], "CPF": d.get("doador_cpf_mascarado") or "—",
              "candidato": d["candidato"], "cargo": d["cargo"],
              "eleição": d.get("ano_eleicao"), "valor": _moeda(d["valor"]),
              "fonte": "TSE"} for d in dados["doacoes"]],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("sem doações relacionadas.")

    # Exportar dossiê.
    md = gerar_markdown(dados)
    st.download_button("⤓ dossiê (.md)", md, file_name=f"dossie_{cnpj}.md", mime="text/markdown")
    st.download_button("⤓ dossiê (.html)", gerar_html(md, titulo=f"Dossiê {cnpj}"),
                       file_name=f"dossie_{cnpj}.html", mime="text/html")


def pagina_contratos(conn):
    st.subheader("▣ contratos")
    # Filtros (Bug 3).
    mods = ["(todas)"] + consultas.modalidades(conn)
    orgs = ["(todos)"] + consultas.orgaos(conn)
    f1, f2 = st.columns(2)
    modalidade = f1.selectbox("modalidade", mods)
    orgao = f2.selectbox("órgão", orgs)
    f3, f4, f5 = st.columns(3)
    valor_min = f3.number_input("valor mínimo (R$)", min_value=0.0, value=0.0, step=1000.0)
    data_ini = f4.text_input("de (AAAA-MM-DD)", value="")
    data_fim = f5.text_input("até (AAAA-MM-DD)", value="")

    contratos = consultas.listar_contratos(
        conn, limite=500,
        modalidade=None if modalidade == "(todas)" else modalidade,
        orgao=None if orgao == "(todos)" else orgao,
        valor_min=valor_min or None,
        data_ini=data_ini.strip() or None,
        data_fim=data_fim.strip() or None,
    )
    st.caption(f"{len(contratos)} contrato(s).")
    if contratos:
        st.dataframe(
            [{"data": c["data"], "órgão": c["orgao"], "objeto": (c["objeto"] or "")[:80],
              "modalidade": c["modalidade"], "valor": _moeda(c["valor"]),
              "fornecedor": c["fornecedor_nome"] or "—", "fonte": c["fonte"]}
             for c in contratos],
            width="stretch", hide_index=True,
        )
    else:
        st.info("nenhum contrato com esses filtros.")


# ---------------------------------------------------------------------------
def main():
    st.markdown(
        "<div class='dev-header'>"
        "<span class='title'>OBSERVATÓRIO // BARRETOS</span>"
        "<span class='sub'><span class='sq sq-green'></span>contratações públicas · indícios rastreáveis</span>"
        "</div>",
        unsafe_allow_html=True,
    )

    paginas = {
        "visão geral": pagina_visao_geral,
        "ranking": pagina_ranking,
        "buscar": pagina_buscar,
        "perfil": pagina_perfil,
        "contratos": pagina_contratos,
    }
    with st.sidebar:
        st.markdown(
            "<div class='mono-dim'><span class='sq sq-green'></span>SYSTEM ONLINE</div>",
            unsafe_allow_html=True,
        )
        st.markdown(f"<div class='mono-dim'>db · {config.DB_PATH.name}</div>", unsafe_allow_html=True)
        st.markdown("---")
        nav_padrao = st.session_state.get("nav", "visão geral")
        escolha = st.radio("navegação", list(paginas), index=list(paginas).index(nav_padrao))
        st.session_state["nav"] = escolha
        st.caption("indícios sujeitos a apuração — nunca veredito.")

    try:
        conn = conectar()
        paginas[escolha](conn)
    except sqlite3.OperationalError:
        st.error("banco não encontrado/iniciado. Rode `python -m src.db` e os coletores.")


if __name__ == "__main__":
    main()
