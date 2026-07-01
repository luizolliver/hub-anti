"""
Painel do Observatório — Etapa 10 (Streamlit).

Visual do mockup `observatorio_barretos_mockup.html`: fundo quase preto
(#040404), acento lime (#aaff00), valores de dados em matrix-green (#00e639),
JetBrains Mono, cartões de métrica em grade, tabelas densas e flags com borda
vermelha. Navega pelos fornecedores de Barretos, nível de atenção, perfil
completo, rede (empresas irmãs), doações e exportação de dossiê.

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

import html as _html  # noqa: E402
import sqlite3  # noqa: E402

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

import config  # noqa: E402
from src import consultas  # noqa: E402
from src.reports.dossie import gerar_html, gerar_markdown, montar_dossie  # noqa: E402

st.set_page_config(
    page_title="OBSERVATÓRIO // BARRETOS", page_icon="▣",
    layout="wide", initial_sidebar_state="expanded",
)

# --- CSS: porte do mockup ----------------------------------------------------
st.markdown(
    """
    <style>
    @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;500;700&display=swap');
    :root{
      --bg:#040404; --bg1:#0a0a0a; --bg2:#0e0e0e;
      --lime:#aaff00; --lime2:#88cc00; --matrix:#00e639;
      --border:#181818; --border2:#222;
      --txt:#cccccc; --txt2:#555; --txt3:#2a2a2a;
      --red:#ff3b3b; --amber:#ffaa00;
      --mono:'JetBrains Mono',monospace;
    }
    html, body, [class*="css"], .stApp, p, span, div, label, input, td, th, button, [data-baseweb]{
        font-family: var(--mono) !important;
    }
    /* Restaura a fonte dos ícones do Streamlit (senão o botão de recolher a
       sidebar mostra o texto 'keyboard_double_arrow_left' em vez do ícone). */
    [data-testid="stIconMaterial"]{
        font-family: 'Material Symbols Rounded' !important;
    }
    .stApp{ background: var(--bg); color: var(--txt); }

    /* Esconde o cromo do Streamlit, MAS mantém o controle de abrir/fechar a
       barra lateral (senão, recolhida, fica sem botão para reabrir). */
    #MainMenu, footer, [data-testid="stToolbar"]{ visibility:hidden; height:0; }
    header[data-testid="stHeader"]{ background:transparent; }
    [data-testid="stSidebarCollapsedControl"],
    [data-testid="stSidebarCollapseButton"], [data-testid="collapsedControl"]{
        visibility:visible !important; }
    [data-testid="stSidebarCollapsedControl"] button,
    [data-testid="collapsedControl"] button{ color:var(--lime) !important; }
    .block-container{ max-width:100% !important; padding:0 22px 40px !important; }

    /* Topbar fixa no topo do conteúdo */
    .topbar{ display:flex; align-items:center; justify-content:space-between;
        padding:11px 4px; border-bottom:1px solid var(--border); margin-bottom:22px; }
    .tbtitle{ font-size:11px; font-weight:700; letter-spacing:.1em; color:var(--txt); }
    .tbmeta{ display:flex; align-items:center; gap:8px; font-size:9px; color:var(--txt2); letter-spacing:.06em; }
    .tbsq{ width:5px; height:5px; background:var(--lime); display:inline-block; }

    /* Cabeçalho de seção */
    .sh{ display:flex; align-items:center; gap:10px; margin:6px 0 20px; }
    .sico{ width:14px; height:14px; border:1px solid var(--txt2); display:inline-flex;
        align-items:center; justify-content:center; font-size:8px; color:var(--txt2); }
    .stitle{ font-size:22px; font-weight:700; color:var(--txt); letter-spacing:-.02em; }
    .sec{ font-size:12px; font-weight:600; color:var(--txt2); margin:22px 0 12px; letter-spacing:.04em; }

    /* Grade de métricas */
    .mgrid{ display:grid; grid-template-columns:repeat(4,1fr); gap:10px; margin-bottom:6px; }
    .mcard{ background:var(--bg2); border:1px solid var(--border); padding:16px 14px; }
    .mcard.alert{ border-color:rgba(255,59,59,.35); }
    .mlabel{ font-size:9px; color:var(--txt2); letter-spacing:.12em; text-transform:uppercase; margin-bottom:10px; }
    .mlabel.red{ color:var(--red); }
    .mval{ font-size:24px; font-weight:700; color:var(--txt); letter-spacing:-.02em; line-height:1; }
    .mval.sm{ font-size:18px; } .mval.red{ color:var(--red); }

    /* Tabelas densas */
    .tbl{ width:100%; border-collapse:collapse; font-size:11px; }
    .tbl th{ padding:7px 10px; text-align:left; color:var(--txt2); font-weight:400;
        letter-spacing:.08em; border-bottom:1px solid var(--border2); font-size:10px; }
    .tbl td{ padding:8px 10px; border-bottom:1px solid #0c0c0c; color:var(--matrix); vertical-align:top; }
    .tbl td:first-child{ color:var(--txt2); white-space:nowrap; }
    .tbl td .nm{ color:var(--txt); } .tbl td .dim{ color:var(--txt2); }
    .tbl tr:hover td{ background:var(--bg1); }
    .tbl a{ color:var(--lime) !important; text-decoration:none; }

    /* Flags (perfil) */
    .flag{ display:flex; align-items:flex-start; gap:10px; padding:9px 12px;
        border-left:2px solid var(--red); background:rgba(255,59,59,.05); margin-bottom:8px; }
    .fsq{ width:8px; height:8px; background:var(--red); flex-shrink:0; margin-top:3px; }
    .flabel{ font-size:9px; font-weight:700; color:var(--red); letter-spacing:.08em; margin-bottom:2px; }
    .ftext{ font-size:10px; color:#ff8080; }
    .okflag{ font-size:11px; color:var(--lime); }

    /* Bloco "json" do cadastro */
    .json{ font-size:11px; line-height:2; color:var(--txt2); }
    .jk{ color:var(--txt2); } .js{ color:var(--matrix); } .jn{ color:var(--amber); font-weight:600; } .jx{ color:var(--red); }
    .twocol{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }

    /* Perfil: nome + tag */
    .pname{ font-size:18px; font-weight:700; color:var(--txt); margin:4px 0 10px; line-height:1.35; }
    .ctag{ font-size:10px; color:var(--matrix); background:rgba(0,230,57,.06);
        border:1px solid rgba(0,230,57,.15); padding:3px 8px; display:inline-block; }
    .badge{ font-size:9px; padding:3px 6px; border:1px solid rgba(255,59,59,.35);
        color:var(--red); letter-spacing:.04em; display:inline-block; margin:0 4px 4px 0; }

    /* Sidebar */
    section[data-testid="stSidebar"]{ background:#020202; border-right:1px solid var(--border); }
    section[data-testid="stSidebar"] *{ color:var(--txt2); }
    section[data-testid="stSidebar"] input[type="radio"]{ accent-color:var(--lime); }
    section[data-testid="stSidebar"] [role="radiogroup"] label:has(input:checked) p{ color:var(--lime) !important; }
    .slogo{ font-size:9px; color:var(--txt2); letter-spacing:.06em; line-height:2;
        border-bottom:1px solid var(--border); padding-bottom:12px; margin-bottom:6px; }
    .sst{ display:flex; align-items:center; gap:6px; font-size:9.5px; color:var(--txt2); margin-bottom:4px; }
    .sdot{ width:6px; height:6px; background:var(--lime); display:inline-block; }
    .sfoot{ font-size:9px; color:var(--txt3); line-height:1.7; }

    /* Botões */
    .stButton > button, .stDownloadButton > button{
        background:transparent !important; border:1px solid var(--border2) !important;
        color:var(--txt2) !important; border-radius:0 !important; font-size:10px;
        letter-spacing:.1em; text-transform:uppercase; box-shadow:none !important; }
    .stButton > button:hover, .stDownloadButton > button:hover{
        border-color:var(--lime) !important; color:var(--lime) !important; }

    /* Inputs, selects, números */
    .stTextInput input, .stNumberInput input, textarea,
    [data-baseweb="input"], [data-baseweb="select"] > div{
        background:var(--bg2) !important; border:1px solid var(--border2) !important;
        color:var(--txt) !important; border-radius:0 !important; box-shadow:none !important; }
    .stTextInput input:focus, [data-baseweb="input"]:focus-within{ border-color:rgba(170,255,0,.4) !important; }
    [data-testid="stSlider"] [role="slider"]{ background:var(--lime) !important; }

    /* Caption */
    [data-testid="stCaptionContainer"], [data-testid="stCaptionContainer"] *{ color:var(--txt2) !important; }
    h1,h2,h3,h4{ color:var(--txt) !important; }
    a, a:visited{ color:var(--lime) !important; }
    </style>
    """,
    unsafe_allow_html=True,
)


# ---------------------------------------------------------------------------
# Helpers de apresentação
# ---------------------------------------------------------------------------
@st.cache_resource
def conectar() -> sqlite3.Connection:
    conn = sqlite3.connect(str(config.DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------------------------------------------------------
# Camada de leitura cacheada (@st.cache_data)
# ---------------------------------------------------------------------------
# Cada consulta é calculada uma vez por combinação de argumentos, em vez de
# reprocessar a cada rerun (o ranking, p.ex., avalia ~7 mil fornecedores). A
# conexão é o singleton de `conectar()` (cache_resource) e NÃO entra na chave
# do cache — os wrappers recebem só argumentos hasháveis. Assim há uma fonte
# única por consulta. O botão "recarregar" na barra lateral chama
# `st.cache_data.clear()` para forçar a releitura quando o banco muda.
def _filtros(modalidade=None, orgao=None, valor_min=None, data_ini=None, data_fim=None) -> dict:
    return {"modalidade": modalidade, "orgao": orgao, "valor_min": valor_min,
            "data_ini": data_ini, "data_fim": data_fim}


def _filtro_ativo(f: dict) -> bool:
    return any(f.get(k) for k in ("modalidade", "orgao", "valor_min", "data_ini", "data_fim"))


@st.cache_data(show_spinner=False)
def _metricas() -> dict:
    return consultas.metricas_gerais(conectar())


@st.cache_data(show_spinner=False)
def _modalidades() -> list:
    return consultas.modalidades(conectar())


@st.cache_data(show_spinner=False)
def _orgaos() -> list:
    return consultas.orgaos(conectar())


@st.cache_data(show_spinner=False)
def _ranking(limite, minimo, modalidade, orgao, valor_min, data_ini, data_fim) -> list:
    return consultas.ranking_atencao(
        conectar(), limite=limite, minimo=minimo,
        filtros=_filtros(modalidade, orgao, valor_min, data_ini, data_fim),
    )


@st.cache_data(show_spinner=False)
def _alertas(dias) -> list:
    return consultas.alertas_recentes(conectar(), dias=dias)


@st.cache_data(show_spinner=False)
def _contratos(limite, modalidade, orgao, valor_min, data_ini, data_fim) -> list:
    return consultas.listar_contratos(
        conectar(), limite=limite, modalidade=modalidade, orgao=orgao,
        valor_min=valor_min, data_ini=data_ini, data_fim=data_fim,
    )


@st.cache_data(show_spinner=False)
def _busca_fornecedores(termo, modalidade, orgao, valor_min, data_ini, data_fim) -> list:
    return consultas.buscar_fornecedores(
        conectar(), termo,
        filtros=_filtros(modalidade, orgao, valor_min, data_ini, data_fim),
    )


@st.cache_data(show_spinner=False)
def _busca_objeto(termo) -> list:
    return consultas.buscar_por_objeto(conectar(), termo)


@st.cache_data(show_spinner=False)
def _busca_socios(termo) -> list:
    return consultas.buscar_socios(conectar(), termo)


@st.cache_data(show_spinner=False)
def _dossie_dados(cnpj) -> dict:
    return montar_dossie(conectar(), cnpj)


@st.cache_data(show_spinner=False)
def _dossie_arquivos(cnpj) -> tuple:
    """Gera (markdown, html) do dossiê — só chamado no fluxo de download."""
    dados = _dossie_dados(cnpj)
    md = gerar_markdown(dados)
    return md, gerar_html(md, titulo=f"Dossiê {cnpj}")


def _moeda(v) -> str:
    try:
        return f"R$ {float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def _e(x) -> str:
    """Escapa texto para uso seguro dentro do HTML das tabelas."""
    return _html.escape("" if x is None else str(x))


def _cabecalho(titulo: str) -> None:
    st.markdown(
        f"<div class='sh'><span class='sico'>□</span><h1 class='stitle'>{_e(titulo)}</h1></div>",
        unsafe_allow_html=True,
    )


def _sec(texto: str) -> None:
    st.markdown(f"<div class='sec'>// {_e(texto)}</div>", unsafe_allow_html=True)


def _tbl(headers: list[str], linhas: list[list[str]], classes: str = "tbl") -> None:
    """Renderiza uma tabela HTML densa. As células já vêm como HTML pronto."""
    if not linhas:
        st.caption("— sem dados —")
        return
    th = "".join(f"<th>{_e(h)}</th>" for h in headers)
    trs = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in row) + "</tr>" for row in linhas)
    st.markdown(
        f"<table class='{classes}'><thead><tr>{th}</tr></thead><tbody>{trs}</tbody></table>",
        unsafe_allow_html=True,
    )


def _mgrid(cards: list[tuple]) -> None:
    """cards = [(label, valor_str, alerta_bool), ...] em grade de 4 colunas."""
    blocos = []
    for label, valor, alerta in cards:
        cls = "mcard alert" if alerta else "mcard"
        lcls = "mlabel red" if alerta else "mlabel"
        vcls = "mval red" if alerta else ("mval sm" if len(str(valor)) > 9 else "mval")
        blocos.append(
            f"<div class='{cls}'><div class='{lcls}'>{_e(label)}</div>"
            f"<div class='{vcls}'>{_e(valor)}</div></div>"
        )
    st.markdown(f"<div class='mgrid'>{''.join(blocos)}</div>", unsafe_allow_html=True)


def _badges(codigos) -> str:
    return "".join(f"<span class='badge'>{_e(c)}</span>" for c in codigos)


def _link_pncp(c: dict) -> str | None:
    if (c.get("fonte") or "") != "PNCP" or not c.get("id_origem"):
        return None
    partes = str(c["id_origem"]).strip("/").split("/")
    if len(partes) >= 4 and partes[0] == "contratos":
        return f"https://pncp.gov.br/app/contratos/{partes[1]}/{partes[2]}/{partes[3]}"
    return "https://pncp.gov.br"


def _ir_para_perfil(cnpj: str) -> None:
    """Callback de navegação (on_click): troca de página sem `st.rerun` manual.

    O clique do botão já dispara um rerun; alterar `session_state` aqui (antes
    dos widgets serem reinstanciados) faz o radio `key="nav"` refletir 'perfil'.
    """
    st.session_state["cnpj"] = cnpj
    st.session_state["nav"] = "perfil"


def filtros_ui(key_prefix: str) -> dict:
    """
    Controles de filtro reutilizáveis (modalidade, órgão, valor mínimo, período)
    para as páginas de contratos, ranking e busca. `key_prefix` isola o estado
    de cada página. Retorna um dict de filtros (None onde vazio).
    """
    with st.expander("filtros", expanded=False):
        mods = ["(todas)"] + _modalidades()
        orgs = ["(todos)"] + _orgaos()
        c1, c2 = st.columns(2)
        modalidade = c1.selectbox("modalidade", mods, key=f"{key_prefix}_mod")
        orgao = c2.selectbox("órgão", orgs, key=f"{key_prefix}_org")
        c3, c4, c5 = st.columns(3)
        valor_min = c3.number_input("valor mínimo (R$)", min_value=0.0, value=0.0,
                                    step=1000.0, key=f"{key_prefix}_vmin")
        data_ini = c4.text_input("de (AAAA-MM-DD)", value="", key=f"{key_prefix}_di")
        data_fim = c5.text_input("até (AAAA-MM-DD)", value="", key=f"{key_prefix}_df")
    return _filtros(
        None if modalidade == "(todas)" else modalidade,
        None if orgao == "(todos)" else orgao,
        valor_min or None,
        data_ini.strip() or None,
        data_fim.strip() or None,
    )


# ---------------------------------------------------------------------------
# Páginas
# ---------------------------------------------------------------------------
def pagina_visao_geral():
    _cabecalho("visão geral")
    m = _metricas()
    _mgrid([
        ("fornecedores", f"{m['fornecedores']:,}", False),
        ("empresas (QSA)", f"{m['empresas_enriquecidas']:,}", False),
        ("R$ pago (TCE)", _moeda(m["total_pago"]), False),
        ("contratos", f"{m['contratos']:,}", False),
        ("despesas", f"{m['despesas']:,}", False),
        ("sócios", f"{m['socios']:,}", False),
        ("sanções cruzadas", f"{m['sancoes']:,}", m["sancoes"] > 0),
        ("doações ligadas", f"{m['doacoes']:,}", False),
    ])

    _sec("topo do ranking de atenção")
    rank = _ranking(10, 1, None, None, None, None, None)
    if rank:
        linhas = [[
            str(r["nivel_atencao"]),
            f"<span class='dim'>{_e(r['cnpj'])}</span>",
            f"<span class='nm'>{_e((r['nome'] or '—')[:40])}</span>",
            _moeda(r["valor_total"]),
            f"<span class='dim'>{_e(', '.join(r['bandeiras']))}</span>",
        ] for r in rank]
        _tbl(["nível", "cnpj", "fornecedor", "R$ movimentado", "bandeiras"], linhas)
    else:
        st.info("sem bandeiras ainda — rode os coletores e o enriquecimento (Etapas 4/5).")

    _sec("alertas recentes (últimos 90 dias)")
    alertas = _alertas(90)
    if alertas:
        st.caption(f"{len(alertas)} contrato(s) recente(s) com fornecedor já sinalizado.")
        linhas = [[
            f"<span class='dim'>{_e(a['data'])}</span>",
            f"<span class='nm'>{_e((a['fornecedor'] or '—')[:34])}</span>",
            f"<span class='dim'>{_e((a['orgao'] or '—')[:28])}</span>",
            _moeda(a["valor"]),
            f"<span class='dim'>{_e(', '.join(a['bandeiras']))}</span>",
        ] for a in alertas]
        _tbl(["data", "fornecedor", "órgão", "valor", "bandeiras"], linhas)
    else:
        st.caption("nenhum contrato assinado nos últimos 90 dias com bandeira ativa.")


def pagina_ranking():
    _cabecalho("ranking de atenção")
    minimo = st.slider("nível mínimo de atenção", 1, 15, 1)
    limite = st.slider("quantos exibir", 10, 200, 50, step=10)
    f = filtros_ui("rank")
    rank = _ranking(limite, minimo, f["modalidade"], f["orgao"], f["valor_min"],
                    f["data_ini"], f["data_fim"])
    st.caption(f"{len(rank)} fornecedores com nível ≥ {minimo}")
    if _filtro_ativo(f):
        st.caption("ℹ o filtro só seleciona quem tem contrato correspondente — "
                   "o nível e as bandeiras refletem o histórico completo do fornecedor.")
    for r in rank:
        cols = st.columns([1, 5, 3, 2])
        cols[0].markdown(
            f"<span style='color:var(--lime);font-size:18px;font-weight:700'>"
            f"· {r['nivel_atencao']}</span>",
            unsafe_allow_html=True,
        )
        cols[1].markdown(
            f"<div style='color:var(--txt);font-weight:600;font-size:12px'>{_e(r['nome'] or '—')}</div>"
            f"<div style='color:var(--matrix);font-size:10px'>{_e(r['cnpj'])}</div>",
            unsafe_allow_html=True,
        )
        cols[2].markdown(_badges(r["bandeiras"]), unsafe_allow_html=True)
        cols[3].button("perfil ▸", key=f"go_{r['cnpj']}",
                       on_click=_ir_para_perfil, args=(r["cnpj"],))


def pagina_buscar():
    _cabecalho("buscar")
    modo = st.radio(
        "modo de busca", ["fornecedor", "objeto de contrato", "sócio (CPF ou nome)"],
        horizontal=True,
    )
    filtro = filtros_ui("busca") if modo == "fornecedor" else _filtros()
    termo = st.text_input("termo", placeholder="> digite e tecle enter")
    if not termo:
        return

    if modo == "fornecedor":
        fns = _busca_fornecedores(termo, filtro["modalidade"], filtro["orgao"],
                                  filtro["valor_min"], filtro["data_ini"], filtro["data_fim"])
        if not fns:
            st.warning("nenhum fornecedor encontrado.")
        elif _filtro_ativo(filtro):
            st.caption("ℹ o filtro só seleciona quem tem contrato correspondente — "
                       "o nível/bandeiras no perfil refletem o histórico completo.")
        for f in fns:
            cols = st.columns([6, 3, 2])
            cols[0].markdown(
                f"<div style='color:var(--txt);font-weight:600'>{_e(f['nome'] or '—')}</div>"
                f"<div style='color:var(--matrix);font-size:10px'>{_e(f['cnpj'])}</div>",
                unsafe_allow_html=True,
            )
            cols[1].markdown(f"recebido: {_moeda(f['valor_pago'])}")
            cols[2].button("perfil ▸", key=f"b_{f['cnpj']}",
                           on_click=_ir_para_perfil, args=(f["cnpj"],))

    elif modo == "objeto de contrato":
        contratos = _busca_objeto(termo)
        if not contratos:
            st.warning("nenhum contrato com esse objeto.")
        else:
            st.caption(f"{len(contratos)} contrato(s) com objeto contendo “{termo}”.")
            linhas = [[
                f"<span class='dim'>{_e(c['data'])}</span>",
                f"<span class='nm'>{_e((c['orgao'] or '—')[:26])}</span>",
                f"<span class='dim'>{_e(c['modalidade'])}</span>",
                _moeda(c["valor"]),
                f"<span class='nm'>{_e((c['fornecedor_nome'] or '—')[:24])}</span>",
                _e((c["objeto"] or "")[:70]),
            ] for c in contratos]
            _tbl(["data", "órgão", "modalidade", "valor", "fornecedor", "objeto"], linhas)

    else:  # sócio
        pessoas = _busca_socios(termo)
        if not pessoas:
            st.warning("nenhum sócio encontrado entre as empresas fornecedoras.")
        for p in pessoas:
            cpf = p.get("documento_visivel")
            st.markdown(
                f"<div style='margin-top:10px'><b style='color:var(--txt)'>{_e(p['nome'] or '—')}</b>"
                f" · cpf parcial: <span style='color:var(--matrix)'>{_e(cpf or '—')}</span>"
                f" · {len(p['empresas'])} empresa(s) · total {_moeda(p['total'])}</div>",
                unsafe_allow_html=True,
            )
            for e in p["empresas"]:
                cols = st.columns([6, 3, 2])
                cols[0].markdown(
                    f"<div style='color:var(--txt)'>↳ {_e(e['nome'] or '—')}</div>"
                    f"<div style='color:var(--matrix);font-size:10px'>{_e(e['cnpj'])}</div>",
                    unsafe_allow_html=True,
                )
                cols[1].markdown(_moeda(e["valor"]))
                cols[2].button("perfil ▸", key=f"s_{cpf}_{e['cnpj']}",
                               on_click=_ir_para_perfil, args=(e["cnpj"],))


def _json_cadastro(emp: dict) -> None:
    """Renderiza o cadastro da Receita no estilo 'json' do mockup."""
    def val(v, tipo="s"):
        if v is None or v == "":
            return "<span class='jn'>NULL</span>"
        return f"<span class='j{tipo}'>\"{_e(v)}\"</span>"

    linhas = [
        ("situação", val(emp.get("situacao_cadastral"), "x" if (emp.get("situacao_cadastral") or "").upper() != "ATIVA" else "s")),
        ("especial", val(emp.get("situacao_especial"), "x")),
        ("abertura", val(emp.get("data_inicio_atividade"))),
        ("natureza", val(emp.get("natureza_juridica"))),
        ("porte", val(emp.get("porte"))),
        ("município/UF", val(f"{emp.get('municipio')}/{emp.get('uf')}" if emp.get("municipio") else None)),
    ]
    corpo = "<br>".join(f"&nbsp;&nbsp;<span class='jk'>\"{k}\"</span> : {v}" for k, v in linhas)
    st.markdown(f"<div class='json'>▾ {{<br>{corpo}<br>}}</div>", unsafe_allow_html=True)


def pagina_perfil():
    _cabecalho("perfil do fornecedor")
    st.markdown("<div style='font-size:10px;color:var(--lime);letter-spacing:.1em'>CNPJ</div>",
                unsafe_allow_html=True)
    cnpj = st.text_input("CNPJ", value=st.session_state.get("cnpj", ""), label_visibility="collapsed")
    if not cnpj:
        st.info("informe um CNPJ ou venha do ranking/busca.")
        return
    dados = _dossie_dados(cnpj)
    emp = dados.get("empresa") or {}
    forn = dados.get("fornecedor") or {}
    nome = emp.get("razao_social") or forn.get("nome") or cnpj

    nivel = dados["nivel_atencao"]
    cor_nivel = "var(--red)" if nivel >= 6 else "var(--amber)" if nivel >= 3 else "var(--lime)"
    st.markdown(f"<div class='pname'>{_e(nome)}</div>", unsafe_allow_html=True)
    st.markdown(
        f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:16px'>"
        f"<span class='ctag'>{_e(cnpj)}</span>"
        f"<span style='font-size:10px;color:var(--txt2)'>· nível de atenção:</span>"
        f"<span style='font-size:13px;font-weight:700;color:{cor_nivel}'>{nivel}</span></div>",
        unsafe_allow_html=True,
    )

    if dados["bandeiras"]:
        for b in dados["bandeiras"]:
            st.markdown(
                f"<div class='flag'><div class='fsq'></div><div>"
                f"<div class='flabel'>■ {_e(b.codigo)}</div>"
                f"<div class='ftext'>{_e(b.descricao)}</div></div></div>",
                unsafe_allow_html=True,
            )
    else:
        st.markdown("<div class='okflag'>nenhuma bandeira disparada.</div>", unsafe_allow_html=True)

    col1, col2 = st.columns(2)
    with col1:
        _sec("cadastro (Receita)")
        if emp:
            _json_cadastro(emp)
        else:
            st.caption("não enriquecido (Etapa 4).")
        _sec("sócios (QSA)")
        if dados["socios"]:
            linhas = [[
                f"<span class='nm'>{_e(s['nome_socio'])}</span>",
                f"<span class='dim'>{_e(s.get('qualificacao') or '—')}</span>",
                _e(s.get("tipo_socio") or "—"),
            ] for s in dados["socios"]]
            _tbl(["sócio", "qualificação", "tipo"], linhas)
        else:
            st.caption("sem QSA.")
    with col2:
        _sec("dinheiro recebido (TCE)")
        if dados["despesas_por_evento"]:
            linhas = [[
                f"<span class='nm'>{_e(r['evento'])}</span>", str(r["n"]), _moeda(r["soma"]),
            ] for r in dados["despesas_por_evento"]]
            _tbl(["evento", "linhas", "valor"], linhas)
        else:
            st.caption("sem despesas.")
        va = dados.get("valor_por_ano") or {}
        if va:
            _sec("valor contratado por ano")
            st.bar_chart(
                pd.DataFrame({"valor": list(va.values())}, index=list(va.keys())),
                color="#00e639", height=200,
            )

    _sec("rede societária (empresas irmãs)")
    irmas = dados.get("irmas") or []
    if irmas:
        linhas = [[
            f"<span class='nm'>{_e((p['nome'] or '—')[:36])}</span>",
            f"<span class='dim'>{_e(p['cnpj'])}</span>",
            _moeda(p["valor"]),
            f"<span class='nm'>{_e(p['socio_comum'] or '—')}</span>",
        ] for p in irmas]
        _tbl(["empresa", "cnpj", "R$ recebido", "sócio em comum"], linhas)
    else:
        st.caption("sem empresas irmãs (nenhum sócio em comum).")

    _sec("contratos individuais")
    cs = dados.get("contratos") or []
    if cs:
        st.caption(f"{len(cs)} contrato(s).")
        linhas = []
        for c in cs:
            link = _link_pncp(c)
            pncp = f"<a href='{link}' target='_blank'>abrir</a>" if link else "—"
            linhas.append([
                f"<span class='dim'>{_e(c['data'])}</span>",
                f"<span class='nm'>{_e((c['orgao'] or '—')[:26])}</span>",
                f"<span class='dim'>{_e(c['modalidade'])}</span>",
                _moeda(c["valor"]),
                _e((c["objeto"] or "")[:60]),
                f"<span class='dim'>{_e(c['fonte'])}</span>",
                pncp,
            ])
        _tbl(["data", "órgão", "modalidade", "valor", "objeto", "fonte", "pncp"], linhas)
    else:
        st.caption("sem contratos vinculados a este CNPJ.")

    cs1, cs2 = st.columns(2)
    with cs1:
        _sec("sanções")
        if dados["sancoes"]:
            linhas = [[
                _e(s["fonte"]), f"<span class='nm'>{_e(s['categoria'])}</span>",
                f"<span class='dim'>{_e(s.get('nome_sancionado'))}</span>", _e(s["vinculo"]),
            ] for s in dados["sancoes"]]
            _tbl(["fonte", "categoria", "nome sancionado", "vínculo"], linhas)
        else:
            st.caption("sem sanções cruzadas.")
    with cs2:
        _sec("doações relacionadas (TSE)")
        if dados["doacoes"]:
            linhas = [[
                f"<span class='nm'>{_e((d['doador_nome'] or '—')[:22])}</span>",
                f"<span class='dim'>{_e(d.get('doador_cpf_mascarado') or '—')}</span>",
                f"<span class='nm'>{_e((d['candidato'] or '—')[:20])}</span>",
                _e(d.get("ano_eleicao")),
                _moeda(d["valor"]),
            ] for d in dados["doacoes"]]
            _tbl(["doador", "cpf", "candidato", "eleição", "valor"], linhas)
        else:
            st.caption("sem doações relacionadas.")

    # Dossiê só sob demanda: só geramos o markdown/html quando o usuário pede
    # (evita renderizar o documento a cada abertura de perfil).
    _sec("dossiê")
    st.session_state.setdefault("gerar_dossie", None)
    if st.button("gerar dossiê", key=f"gd_{cnpj}"):
        st.session_state["gerar_dossie"] = cnpj
    if st.session_state.get("gerar_dossie") == cnpj:
        md, html = _dossie_arquivos(cnpj)
        d1, d2 = st.columns(2)
        d1.download_button("⤓ dossiê (.md)", md, file_name=f"dossie_{cnpj}.md",
                           mime="text/markdown")
        d2.download_button("⤓ dossiê (.html)", html, file_name=f"dossie_{cnpj}.html",
                           mime="text/html")
    else:
        st.caption("clique em “gerar dossiê” para produzir os arquivos .md/.html.")


def pagina_contratos():
    _cabecalho("contratos")
    f = filtros_ui("contr")
    contratos = _contratos(500, f["modalidade"], f["orgao"], f["valor_min"],
                           f["data_ini"], f["data_fim"])
    st.caption(f"{len(contratos)} contrato(s).")
    if contratos:
        linhas = [[
            f"<span class='dim'>{_e(c['data'])}</span>",
            f"<span class='nm'>{_e((c['orgao'] or '—')[:34])}</span>",
            _e((c["objeto"] or "")[:60]),
            f"<span class='dim'>{_e(c['modalidade'])}</span>",
            _moeda(c["valor"]),
            f"<span class='nm'>{_e((c['fornecedor_nome'] or '—')[:24])}</span>",
            f"<span class='dim'>{_e(c['fonte'])}</span>",
        ] for c in contratos]
        _tbl(["data", "órgão", "objeto", "modalidade", "valor", "fornecedor", "fonte"], linhas)
    else:
        st.info("nenhum contrato com esses filtros.")


# ---------------------------------------------------------------------------
def main():
    st.markdown(
        "<div class='topbar'><span class='tbtitle'>OBSERVATÓRIO // BARRETOS</span>"
        "<span class='tbmeta'><span class='tbsq'></span>CONTRATAÇÕES PÚBLICAS · INDÍCIOS RASTREÁVEIS</span>"
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
            "<div class='slogo'>OBSERVATÓRIO // BARRETOS<br>"
            "<span style='color:var(--txt3)'>v2.1.0 · sqlite3</span></div>",
            unsafe_allow_html=True,
        )
        st.markdown("<div class='sst'><span class='sdot'></span>SYSTEM ONLINE</div>",
                    unsafe_allow_html=True)
        st.markdown(f"<div class='sst'>db · {config.DB_PATH.name}</div>", unsafe_allow_html=True)
        st.markdown("<div style='font-size:9px;color:var(--txt3);letter-spacing:.14em;"
                    "text-transform:uppercase;margin:16px 0 4px'>// navegação</div>",
                    unsafe_allow_html=True)
        # `key="nav"` faz o radio ser a única fonte da página atual; os callbacks
        # de navegação (perfil ▸) escrevem em session_state["nav"] e o radio
        # reflete na próxima renderização — sem index= nem escrita dupla.
        st.session_state.setdefault("nav", "visão geral")
        escolha = st.radio("navegação", list(paginas), key="nav",
                           label_visibility="collapsed")
        if st.button("↻ recarregar dados"):
            st.cache_data.clear()
            st.rerun()
        st.markdown("<div class='sfoot'>indícios sujeitos a apuração — nunca veredito.</div>",
                    unsafe_allow_html=True)

    try:
        conectar()  # valida a conexão cedo (erro amigável se o banco não existe)
        paginas[escolha]()
    except sqlite3.OperationalError:
        st.error("banco não encontrado/iniciado. Rode `python -m src.db` e os coletores.")


if __name__ == "__main__":
    main()
