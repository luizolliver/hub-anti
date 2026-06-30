"""
Rede societária — Etapa 7.

Monta um grafo (`networkx`) ligando empresas aos seus sócios para achar
conluio e "empresas da mesma turma": pares com **sócio em comum** e
**clusters** (grupos conectados). Exporta uma visualização `pyvis` (HTML).

Identidade de pessoa: usa a chave robusta da Etapa 4 — nome normalizado +
dígitos visíveis do CPF. Sócio PF com dígitos = vínculo **forte**; sem dígitos
= **provável** (ver `nivel_vinculo_socio`). Sócio PJ é tratado como outra
empresa (liga empresa↔empresa pela `cnpj_socio`), revelando holdings/donas
em comum.

Princípio de ouro: a construção e a detecção são funções puras (recebem linhas
de sócios), testáveis offline. Só `exportar_html` e `*_do_banco` tocam I/O.
"""

from __future__ import annotations

import sqlite3

import networkx as nx

from src.normalize.entidades import normalizar_nome


def _id_empresa(cnpj: str) -> str:
    return f"emp:{cnpj}"


def _id_pessoa(nome_chave: str, visivel: str | None) -> str:
    return f"pes:{nome_chave}|{visivel or ''}"


# ---------------------------------------------------------------------------
# Construção do grafo (função pura)
# ---------------------------------------------------------------------------
def construir_grafo(socios: list[dict], empresas: dict[str, str] | None = None) -> nx.Graph:
    """
    Constrói o grafo a partir de linhas de sócios.

    Cada linha (dict) deve ter: cnpj_empresa, nome_socio, nome_socio_chave,
    documento_visivel, tipo_socio ('PF'/'PJ'), cnpj_socio, qualificacao.
    `empresas` mapeia cnpj→nome (opcional, para rotular os nós de empresa).

    Nós: empresas ('tipo'='empresa') e pessoas ('tipo'='pessoa'). Sócio PJ vira
    um nó de empresa (liga empresa↔empresa).
    """
    empresas = empresas or {}
    g = nx.Graph()

    for s in socios:
        cnpj_emp = s["cnpj_empresa"]
        ide = _id_empresa(cnpj_emp)
        g.add_node(ide, tipo="empresa", cnpj=cnpj_emp, nome=empresas.get(cnpj_emp))

        if s.get("tipo_socio") == "PJ" and s.get("cnpj_socio"):
            # Sócio é uma empresa: liga empresa↔empresa.
            idp = _id_empresa(s["cnpj_socio"])
            g.add_node(idp, tipo="empresa", cnpj=s["cnpj_socio"],
                       nome=empresas.get(s["cnpj_socio"]) or s.get("nome_socio"))
        else:
            chave = s.get("nome_socio_chave") or normalizar_nome(s.get("nome_socio"))
            if not chave:
                continue
            visivel = s.get("documento_visivel")
            idp = _id_pessoa(chave, visivel)
            g.add_node(idp, tipo="pessoa", nome=s.get("nome_socio"),
                       visivel=visivel, forte=bool(visivel))

        g.add_edge(ide, idp, qualificacao=s.get("qualificacao"))

    return g


# ---------------------------------------------------------------------------
# Detecções (funções puras)
# ---------------------------------------------------------------------------
def pares_socio_em_comum(g: nx.Graph) -> list[dict]:
    """
    Lista pares de empresas que compartilham um mesmo sócio.

    `nivel`: 'forte' quando a pessoa tem dígitos visíveis do CPF (quase imune a
    homônimo); 'provavel' quando o casamento foi só por nome. Para sócio PJ em
    comum (uma empresa dona de duas), `nivel`='cnpj'.
    """
    pares: list[dict] = []
    for no, dados in g.nodes(data=True):
        vizinhas = [v for v in g.neighbors(no) if g.nodes[v].get("tipo") == "empresa"]
        if len(vizinhas) < 2:
            continue
        if dados.get("tipo") == "pessoa":
            nivel = "forte" if dados.get("forte") else "provavel"
            rotulo = dados.get("nome")
        elif dados.get("tipo") == "empresa":
            nivel = "cnpj"  # uma EMPRESA é sócia comum (holding/dona)
            rotulo = dados.get("nome") or dados.get("cnpj")
        else:
            continue
        for i in range(len(vizinhas)):
            for j in range(i + 1, len(vizinhas)):
                a, b = sorted((g.nodes[vizinhas[i]]["cnpj"], g.nodes[vizinhas[j]]["cnpj"]))
                pares.append({"empresa_a": a, "empresa_b": b, "elo": rotulo, "nivel": nivel})
    return pares


def clusters(g: nx.Graph, min_empresas: int = 2) -> list[list[str]]:
    """
    Componentes conectados com pelo menos `min_empresas` empresas — grupos de
    empresas ligadas por sócios/donas em comum.
    """
    out: list[list[str]] = []
    for comp in nx.connected_components(g):
        cnpjs = sorted(
            g.nodes[n]["cnpj"] for n in comp if g.nodes[n].get("tipo") == "empresa"
        )
        if len(cnpjs) >= min_empresas:
            out.append(cnpjs)
    return out


# ---------------------------------------------------------------------------
# Acesso ao banco + exportação
# ---------------------------------------------------------------------------
def construir_grafo_do_banco(conn: sqlite3.Connection) -> nx.Graph:
    """Lê `socios` e `fornecedores`/`empresas` do banco e monta o grafo."""
    socios = [dict(r) for r in conn.execute(
        "SELECT cnpj_empresa, nome_socio, nome_socio_chave, documento_visivel, "
        "tipo_socio, cnpj_socio, qualificacao FROM socios"
    )]
    empresas = {
        r["cnpj"]: r["nome"]
        for r in conn.execute("SELECT cnpj, nome FROM fornecedores")
    }
    # Completa nomes com a tabela empresas quando houver.
    for r in conn.execute("SELECT cnpj, razao_social FROM empresas"):
        empresas.setdefault(r["cnpj"], r["razao_social"])
    return construir_grafo(socios, empresas)


def exportar_html(g: nx.Graph, caminho: str, foco_cnpj: str | None = None, raio: int = 1) -> str:
    """
    Exporta um HTML interativo (`pyvis`). Se `foco_cnpj` for dado, exporta só a
    vizinhança (ego-grafo) daquela empresa, no raio indicado. Retorna o caminho.
    """
    from pyvis.network import Network

    alvo = g
    if foco_cnpj:
        centro = _id_empresa(foco_cnpj)
        if centro in g:
            alvo = nx.ego_graph(g, centro, radius=raio)

    net = Network(height="700px", width="100%", notebook=False, directed=False)
    for no, d in alvo.nodes(data=True):
        empresa = d.get("tipo") == "empresa"
        net.add_node(
            no,
            label=(d.get("nome") or d.get("cnpj") or no) if empresa else (d.get("nome") or no),
            color="#e74c3c" if empresa else "#3498db",
            shape="dot" if empresa else "triangle",
            title=f"{d.get('tipo')}: {d.get('nome') or d.get('cnpj')}",
        )
    for a, b, d in alvo.edges(data=True):
        net.add_edge(a, b, title=d.get("qualificacao") or "")

    net.write_html(caminho, notebook=False)
    return caminho
