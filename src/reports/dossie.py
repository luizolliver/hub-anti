"""
Dossiês / relatórios — Etapa 9.

Dado um CNPJ de fornecedor, junta tudo o que o observatório sabe (cadastro,
dinheiro recebido, contratos, bandeiras, sócios, rede, sanções e doações) num
documento **Markdown**, com as **fontes** de cada dado e o **aviso padrão** de
que são *indícios sujeitos a apuração*. Converte para HTML e, se o ambiente
tiver `weasyprint` (GTK), também para PDF.

Separação: `montar_dossie` (lê o banco) → `gerar_markdown` (função pura sobre o
dict de dados, testável) → `gerar_html` / `gerar_pdf`.
"""

from __future__ import annotations

import sqlite3

import config
from src.analysis.flags import (
    concentracao_fornecedor,
    fornecedor_ou_socio_sancionado,
    situacao_cadastral_irregular,
)
from src.analysis.rede import construir_grafo_do_banco, pares_socio_em_comum

AVISO = (
    "> ⚠️ **Aviso.** Este dossiê reúne *indícios* extraídos de dados públicos "
    "oficiais. Indício não é acusação nem prova de irregularidade. Cada item "
    "remete à sua fonte e merece **apuração humana**. Casamentos por nome são "
    "falíveis (homônimos)."
)

FONTES = {
    "PNCP": "https://pncp.gov.br",
    "TCE-SP (Despesas)": "https://transparencia.tce.sp.gov.br",
    "Receita Federal/QSA (BrasilAPI)": "https://brasilapi.com.br",
    "CEIS/CNEP (Portal da Transparência)": "https://portaldatransparencia.gov.br",
    "TSE (doações)": "https://dadosabertos.tse.jus.br",
}


# ---------------------------------------------------------------------------
# Coleta de dados do banco
# ---------------------------------------------------------------------------
def montar_dossie(conn: sqlite3.Connection, cnpj: str) -> dict:
    """Reúne, do banco, tudo o que se sabe sobre um CNPJ."""
    g = conn.execute
    empresa = g("SELECT * FROM empresas WHERE cnpj = ?", (cnpj,)).fetchone()
    fornecedor = g("SELECT * FROM fornecedores WHERE cnpj = ?", (cnpj,)).fetchone()

    despesas_evento = g(
        "SELECT evento, COUNT(*) n, COALESCE(SUM(valor),0) soma FROM despesas "
        "WHERE fornecedor_documento = ? GROUP BY evento ORDER BY soma DESC",
        (cnpj,),
    ).fetchall()
    contratos = g(
        "SELECT data, modalidade, valor, objeto, orgao FROM contratos "
        "WHERE fornecedor_cnpj = ? ORDER BY valor DESC LIMIT 20",
        (cnpj,),
    ).fetchall()
    socios = g(
        "SELECT nome_socio, qualificacao, tipo_socio FROM socios WHERE cnpj_empresa = ?",
        (cnpj,),
    ).fetchall()
    sancoes = g(
        "SELECT fonte, categoria, vinculo, nome_sancionado, data_inicio, data_fim, "
        "orgao_sancionador FROM sancoes_encontradas WHERE alvo_cnpj = ?",
        (cnpj,),
    ).fetchall()
    doacoes = g(
        "SELECT doador_nome, candidato, cargo, partido, valor, data, vinculo "
        "FROM doacoes_relacionadas WHERE alvo_cnpj = ? ORDER BY valor DESC",
        (cnpj,),
    ).fetchall()

    # Rede: pares com sócio/dona em comum envolvendo este CNPJ.
    nomes = {r["cnpj"]: r["nome"] for r in g("SELECT cnpj, nome FROM fornecedores")}
    grafo = construir_grafo_do_banco(conn)
    pares = [
        {**p, "outro_cnpj": p["empresa_b"] if p["empresa_a"] == cnpj else p["empresa_a"]}
        for p in pares_socio_em_comum(grafo)
        if cnpj in (p["empresa_a"], p["empresa_b"])
    ]
    for p in pares:
        p["outro_nome"] = nomes.get(p["outro_cnpj"])

    # Bandeiras que dá para computar a partir do que temos.
    total_pago = g("SELECT COALESCE(SUM(valor_pago),0) FROM fornecedores").fetchone()[0]
    sanc_dicts = [dict(s) for s in sancoes]
    bandeiras = [
        b for b in (
            situacao_cadastral_irregular(
                empresa["situacao_cadastral"] if empresa else None,
                empresa["situacao_especial"] if empresa else None,
            ),
            fornecedor_ou_socio_sancionado(sanc_dicts),
            concentracao_fornecedor(
                fornecedor["valor_pago"] if fornecedor else None,
                total_pago,
                limiar_fracao=config.LIMIAR_CONCENTRACAO,
            ),
        )
        if b is not None
    ]

    return {
        "cnpj": cnpj,
        "empresa": dict(empresa) if empresa else None,
        "fornecedor": dict(fornecedor) if fornecedor else None,
        "despesas_por_evento": [dict(r) for r in despesas_evento],
        "contratos": [dict(r) for r in contratos],
        "socios": [dict(r) for r in socios],
        "sancoes": sanc_dicts,
        "doacoes": [dict(r) for r in doacoes],
        "rede": pares,
        "bandeiras": bandeiras,
        "nivel_atencao": sum(b.peso for b in bandeiras),
    }


# ---------------------------------------------------------------------------
# Renderização (função pura sobre o dict)
# ---------------------------------------------------------------------------
def _moeda(v) -> str:
    try:
        return f"R$ {float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def gerar_markdown(dados: dict) -> str:
    """Função pura: dict do dossiê → Markdown. Não acessa o banco."""
    emp = dados.get("empresa") or {}
    forn = dados.get("fornecedor") or {}
    nome = emp.get("razao_social") or forn.get("nome") or dados["cnpj"]

    L: list[str] = []
    L.append(f"# Dossiê — {nome}")
    L.append(f"**CNPJ:** {dados['cnpj']}  ")
    L.append(f"**Nível de atenção:** {dados.get('nivel_atencao', 0)}")
    L.append("")
    L.append(AVISO)
    L.append("")

    # Bandeiras
    L.append("## Bandeiras (indícios)")
    bandeiras = dados.get("bandeiras") or []
    if bandeiras:
        for b in bandeiras:
            L.append(f"- **{b.codigo}** (peso {b.peso}): {b.descricao}")
            if b.evidencia:
                L.append(f"  - evidência: `{b.evidencia}`")
    else:
        L.append("_Nenhuma bandeira disparada com os dados atuais._")
    L.append("")

    # Cadastro
    L.append("## Empresa (cadastro — Receita Federal)")
    if emp:
        L.append(f"- Situação cadastral: **{emp.get('situacao_cadastral') or '—'}**"
                 + (f" / especial: **{emp['situacao_especial']}**" if emp.get("situacao_especial") else ""))
        L.append(f"- Abertura: {emp.get('data_inicio_atividade') or '—'}")
        L.append(f"- Natureza jurídica: {emp.get('natureza_juridica') or '—'} | Porte: {emp.get('porte') or '—'}")
        L.append(f"- Município/UF: {emp.get('municipio') or '—'}/{emp.get('uf') or '—'}")
    else:
        L.append("_Cadastro não enriquecido (rode a Etapa 4 para este CNPJ)._")
    L.append("")

    # Dinheiro recebido (TCE)
    L.append("## Dinheiro recebido (TCE-SP — Despesas)")
    de = dados.get("despesas_por_evento") or []
    if de:
        L.append("| Evento | Linhas | Valor |")
        L.append("|---|---:|---:|")
        for r in de:
            L.append(f"| {r['evento']} | {r['n']} | {_moeda(r['soma'])} |")
    else:
        L.append("_Sem despesas registradas para este CNPJ._")
    L.append("")

    # Contratos (PNCP)
    L.append("## Contratos (PNCP)")
    cs = dados.get("contratos") or []
    if cs:
        L.append("| Data | Modalidade | Valor | Objeto |")
        L.append("|---|---|---:|---|")
        for c in cs:
            obj = (c.get("objeto") or "")[:60]
            L.append(f"| {c.get('data') or '—'} | {c.get('modalidade') or '—'} | {_moeda(c.get('valor'))} | {obj} |")
    else:
        L.append("_Sem contratos vinculados a este CNPJ no PNCP (fornecedor pode estar nulo)._")
    L.append("")

    # Sócios
    L.append("## Sócios (QSA)")
    socios = dados.get("socios") or []
    if socios:
        for s in socios:
            L.append(f"- {s.get('nome_socio')} — {s.get('qualificacao') or '—'} ({s.get('tipo_socio') or '—'})")
    else:
        L.append("_Quadro societário não disponível._")
    L.append("")

    # Rede
    L.append("## Rede societária")
    rede = dados.get("rede") or []
    if rede:
        for p in rede:
            L.append(f"- Elo **{p.get('nivel')}** com {p.get('outro_nome') or p.get('outro_cnpj')} "
                     f"(via {p.get('elo')})")
    else:
        L.append("_Nenhum elo de sócio/dona em comum detectado._")
    L.append("")

    # Sanções
    L.append("## Sanções (CEIS/CNEP)")
    sancoes = dados.get("sancoes") or []
    if sancoes:
        for s in sancoes:
            L.append(f"- **{s.get('fonte')}**: {s.get('categoria')} "
                     f"({s.get('data_inicio') or '—'} → {s.get('data_fim') or '—'}) "
                     f"— órgão: {s.get('orgao_sancionador') or '—'} [{s.get('vinculo')}]")
    else:
        L.append("_Sem sanções cruzadas._")
    L.append("")

    # Doações
    L.append("## Doações de campanha (TSE)")
    doacoes = dados.get("doacoes") or []
    if doacoes:
        for d in doacoes:
            L.append(f"- {d.get('doador_nome')} doou {_moeda(d.get('valor'))} para "
                     f"**{d.get('candidato')}** ({d.get('cargo')}/{d.get('partido') or '—'}) "
                     f"em {d.get('data') or '—'} [{d.get('vinculo')}]")
    else:
        L.append("_Nenhuma doação relacionada._")
    L.append("")

    # Fontes
    L.append("## Fontes")
    for nome_fonte, url in FONTES.items():
        L.append(f"- {nome_fonte}: {url}")
    L.append("")
    L.append("_Dossiê gerado automaticamente pelo Observatório de Contratações de Barretos._")

    return "\n".join(L)


def gerar_html(markdown_texto: str, titulo: str = "Dossiê") -> str:
    """Converte o Markdown em HTML (com tabelas) e embute um CSS simples."""
    import markdown as _md

    corpo = _md.markdown(markdown_texto, extensions=["tables"])
    return (
        "<!doctype html><html lang='pt-br'><head><meta charset='utf-8'>"
        f"<title>{titulo}</title><style>"
        "body{font-family:Arial,Helvetica,sans-serif;max-width:900px;margin:2rem auto;"
        "line-height:1.5;color:#222} h1{border-bottom:3px solid #c0392b}"
        "h2{margin-top:1.8rem;color:#c0392b} table{border-collapse:collapse;width:100%}"
        "th,td{border:1px solid #ccc;padding:6px 8px;text-align:left}"
        "blockquote{background:#fdf3f2;border-left:4px solid #c0392b;padding:.5rem 1rem}"
        "code{background:#f4f4f4;padding:1px 4px}</style></head><body>"
        f"{corpo}</body></html>"
    )


def gerar_pdf(html: str, caminho: str) -> str | None:
    """
    Gera PDF a partir do HTML usando weasyprint, SE disponível (precisa de GTK
    no Windows). Retorna o caminho ou None se o weasyprint não estiver presente.
    """
    try:
        from weasyprint import HTML
    except (ImportError, OSError):
        return None
    HTML(string=html).write_pdf(caminho)
    return caminho


def gerar_dossie(conn: sqlite3.Connection, cnpj: str, caminho_base: str) -> dict:
    """
    Orquestra: monta os dados, grava o `.md` e o `.html` em `caminho_base.*` e
    tenta o `.pdf`. Retorna os caminhos gerados.
    """
    dados = montar_dossie(conn, cnpj)
    md = gerar_markdown(dados)
    html = gerar_html(md, titulo=f"Dossiê {cnpj}")

    saidas: dict[str, str] = {}
    with open(f"{caminho_base}.md", "w", encoding="utf-8") as f:
        f.write(md)
    saidas["md"] = f"{caminho_base}.md"
    with open(f"{caminho_base}.html", "w", encoding="utf-8") as f:
        f.write(html)
    saidas["html"] = f"{caminho_base}.html"
    pdf = gerar_pdf(html, f"{caminho_base}.pdf")
    if pdf:
        saidas["pdf"] = pdf
    return saidas
