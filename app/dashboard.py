"""
Painel do Observatório — Etapa 10 (Streamlit, tema "hacker").

Interface de terminal verde-sobre-preto para navegar pelos fornecedores de
Barretos, seu nível de atenção, perfil completo, rede e exportação de dossiê.

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

import streamlit as st  # noqa: E402

import config  # noqa: E402
from src import consultas  # noqa: E402
from src.reports.dossie import gerar_html, gerar_markdown, montar_dossie  # noqa: E402

st.set_page_config(page_title="OBSERVATÓRIO // BARRETOS", page_icon="▣", layout="wide")

# --- CSS: terminal verde ----------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Share+Tech+Mono&display=swap');
    html, body, [class*="css"], .stApp, .stMarkdown, p, span, div, label, input, td, th {
        font-family: 'Share Tech Mono', monospace !important;
    }
    .stApp { background:
        radial-gradient(circle at 50% 0%, #0d160d 0%, #080b08 70%);
        color: #00ff41; }
    h1, h2, h3 { color: #00ff41 !important; text-shadow: 0 0 8px #00ff4180; letter-spacing: 1px; }
    .term-banner {
        border: 1px solid #00ff4140; border-left: 3px solid #00ff41;
        background: #0009; padding: .6rem 1rem; margin-bottom: 1rem;
        white-space: pre; line-height: 1.1; color: #00ff41; text-shadow: 0 0 6px #00ff4160;
    }
    .blink { animation: blink 1.1s steps(2, start) infinite; }
    @keyframes blink { to { visibility: hidden; } }
    .badge { display:inline-block; border:1px solid #00ff4150; border-radius:3px;
        padding:1px 6px; margin:2px; font-size:.8rem; color:#9dffb0; }
    .alert { border-left:3px solid #ff4141; background:#160a0a; color:#ff8a8a;
        padding:.4rem .8rem; margin:.2rem 0; text-shadow:0 0 6px #ff414140; }
    .ok { color:#00ff41; }
    [data-testid="stMetricValue"] { color:#00ff41; text-shadow:0 0 8px #00ff4170; }
    [data-testid="stMetricLabel"] { color:#5cff8a !important; }
    section[data-testid="stSidebar"] { background:#060806; border-right:1px solid #00ff4130; }
    .stDataFrame { border:1px solid #00ff4130; }
    a, a:visited { color:#41ffff !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

BANNER = r"""
 ▄▄▄·▄▄▄▄▄ ·▄▄▄▄· ·▄▄▄▄  ·▄▄▄  OBSERVATÓRIO DE CONTRATAÇÕES PÚBLICAS
 ▐█ ▌▪•██   ▐▄▄·▪ ██▪ ██ ▐▄▄·  BARRETOS / SP  ::  follow the money
 ██ ▄▄ ▐█.▪ ██▪  ▐█· ▐█▌ ██▪   indícios rastreáveis, nunca veredito
"""


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
    c4.metric("contratos (PNCP)", f"{m['contratos']:,}")
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
              "R$ pago": r["valor_pago"], "bandeiras": ", ".join(r["bandeiras"])} for r in rank],
            width="stretch", hide_index=True,
        )
    else:
        st.info("sem bandeiras ainda — rode os coletores e o enriquecimento (Etapas 4/5).")


def pagina_ranking(conn):
    st.subheader("▣ ranking de atenção")
    minimo = st.slider("nível mínimo de atenção", 1, 15, 1)
    limite = st.slider("quantos exibir", 10, 200, 50, step=10)
    rank = consultas.ranking_atencao(conn, limite=limite, minimo=minimo)
    st.caption(f"{len(rank)} fornecedores com nível ≥ {minimo}")
    for r in rank:
        cols = st.columns([1, 5, 3, 2])
        cols[0].markdown(f"### {r['nivel_atencao']}")
        cols[1].markdown(f"**{r['nome'] or '—'}**  \n`{r['cnpj']}`")
        cols[2].markdown(_badges(r["bandeiras"]), unsafe_allow_html=True)
        if cols[3].button("perfil ▸", key=f"go_{r['cnpj']}"):
            st.session_state["cnpj"] = r["cnpj"]
            st.session_state["nav"] = "perfil"
            st.rerun()


def pagina_buscar(conn):
    st.subheader("▣ buscar")
    termo = st.text_input("empresa, CNPJ ou pessoa", placeholder="> digite e tecle enter")
    if not termo:
        return
    fns = consultas.buscar_fornecedores(conn, termo)
    if fns:
        st.markdown("#### fornecedores")
        for f in fns:
            cols = st.columns([6, 3, 2])
            cols[0].markdown(f"**{f['nome'] or '—'}**  \n`{f['cnpj']}`")
            cols[1].markdown(f"pago: {_moeda(f['valor_pago'])}")
            if cols[2].button("perfil ▸", key=f"b_{f['cnpj']}"):
                st.session_state["cnpj"] = f["cnpj"]
                st.session_state["nav"] = "perfil"
                st.rerun()
    pessoas = consultas.buscar_pessoas(conn, termo)
    if pessoas:
        st.markdown("#### pessoas (sócios)")
        st.dataframe(
            [{"nome": p["nome_socio"], "empresa (cnpj)": p["cnpj_empresa"],
              "qualificação": p["qualificacao"], "cpf*": p["documento_visivel"]} for p in pessoas],
            width="stretch", hide_index=True,
        )
    if not fns and not pessoas:
        st.warning("nada encontrado.")


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
    st.markdown(f"`{cnpj}`  ·  nível de atenção: **{dados['nivel_atencao']}**")

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
                [{"evento": r["evento"], "linhas": r["n"], "valor": r["soma"]}
                 for r in dados["despesas_por_evento"]],
                width="stretch", hide_index=True,
            )
        else:
            st.caption("sem despesas.")
        st.markdown("#### rede societária")
        if dados["rede"]:
            for p in dados["rede"]:
                st.write(f"- elo **{p['nivel']}** com {p.get('outro_nome') or p.get('outro_cnpj')} (via {p['elo']})")
        else:
            st.caption("sem elos.")

    st.markdown("#### sanções")
    if dados["sancoes"]:
        st.dataframe(
            [{"fonte": s["fonte"], "categoria": s["categoria"], "início": s["data_inicio"],
              "fim": s["data_fim"], "órgão": s["orgao_sancionador"], "vínculo": s["vinculo"]}
             for s in dados["sancoes"]],
            width="stretch", hide_index=True,
        )
    else:
        st.caption("sem sanções cruzadas.")

    st.markdown("#### doações relacionadas")
    if dados["doacoes"]:
        st.dataframe(
            [{"doador": d["doador_nome"], "candidato": d["candidato"], "cargo": d["cargo"],
              "valor": d["valor"], "data": d["data"], "vínculo": d["vinculo"]}
             for d in dados["doacoes"]],
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
    st.subheader("▣ contratos (PNCP)")
    contratos = consultas.listar_contratos(conn, limite=200)
    if contratos:
        st.dataframe(
            [{"data": c["data"], "órgão": c["orgao"], "modalidade": c["modalidade"],
              "valor": c["valor"], "objeto": (c["objeto"] or "")[:80]} for c in contratos],
            width="stretch", hide_index=True,
        )
    else:
        st.info("sem contratos (rode a Etapa 1).")


# ---------------------------------------------------------------------------
def main():
    st.markdown(f"<div class='term-banner'>{BANNER}</div>", unsafe_allow_html=True)

    paginas = {
        "visão geral": pagina_visao_geral,
        "ranking": pagina_ranking,
        "buscar": pagina_buscar,
        "perfil": pagina_perfil,
        "contratos": pagina_contratos,
    }
    with st.sidebar:
        st.markdown("```\n[ SISTEMA ONLINE ]\n```")
        st.markdown(f"db: `{config.DB_PATH.name}`")
        nav_padrao = st.session_state.get("nav", "visão geral")
        escolha = st.radio("navegação", list(paginas), index=list(paginas).index(nav_padrao))
        st.session_state["nav"] = escolha
        st.markdown("<span class='blink'>█</span> _aguardando comando_", unsafe_allow_html=True)
        st.caption("indícios sujeitos a apuração — nunca veredito.")

    try:
        conn = conectar()
        paginas[escolha](conn)
    except sqlite3.OperationalError:
        st.error("banco não encontrado/iniciado. Rode `python -m src.db` e os coletores.")


if __name__ == "__main__":
    main()
