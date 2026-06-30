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

import datetime
import sqlite3

from src import consultas
from src.analysis.flags import avaliar_fornecedor
from src.normalize.entidades import mascarar_cpf

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
        "SELECT doador_nome, doador_documento, candidato, cargo, partido, valor, data, "
        "ano_eleicao, vinculo FROM doacoes_relacionadas WHERE alvo_cnpj = ? ORDER BY valor DESC",
        (cnpj,),
    ).fetchall()

    # Contratos individuais, empresas-irmãs e série temporal vêm das consultas.
    contratos = consultas.contratos_do_fornecedor(conn, cnpj)
    irmas = consultas.empresas_irmas(conn, cnpj)
    valor_ano = consultas.valor_por_ano(conn, cnpj)

    # Bandeiras: fonte ÚNICA de verdade (idêntica ao ranking).
    avaliacao = avaliar_fornecedor(consultas.contexto_de(conn, cnpj))

    doacoes_fmt = []
    for d in doacoes:
        item = dict(d)
        item["doador_cpf_mascarado"] = mascarar_cpf(d["doador_documento"])
        doacoes_fmt.append(item)

    n_contratos = g("SELECT COUNT(*) FROM contratos").fetchone()[0]
    n_fornec = g("SELECT COUNT(*) FROM fornecedores").fetchone()[0]
    rodape = {
        "gerado_em": datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        "versao_banco": f"{n_contratos} contratos · {n_fornec} fornecedores",
    }

    return {
        "cnpj": cnpj,
        "empresa": dict(empresa) if empresa else None,
        "fornecedor": dict(fornecedor) if fornecedor else None,
        "despesas_por_evento": [dict(r) for r in despesas_evento],
        "contratos": contratos,
        "valor_por_ano": valor_ano,
        "socios": [dict(r) for r in socios],
        "sancoes": [dict(s) for s in sancoes],
        "doacoes": doacoes_fmt,
        "irmas": irmas,
        "bandeiras": avaliacao["bandeiras"],
        "nivel_atencao": avaliacao["nivel_atencao"],
        "rodape": rodape,
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

    # Série temporal
    va = dados.get("valor_por_ano") or {}
    if va:
        L.append("## Valor contratado por ano (TCE-SP)")
        L.append("| Ano | Valor |")
        L.append("|---|---:|")
        for ano in sorted(va):
            L.append(f"| {ano} | {_moeda(va[ano])} |")
        L.append("")

    # Contratos individuais
    L.append("## Contratos individuais")
    cs = dados.get("contratos") or []
    if cs:
        L.append("| Data | Órgão | Modalidade | Valor | Objeto | Fonte |")
        L.append("|---|---|---|---:|---|---|")
        for c in cs:
            obj = (c.get("objeto") or "")[:50]
            L.append(
                f"| {c.get('data') or '—'} | {(c.get('orgao') or '—')[:28]} | "
                f"{c.get('modalidade') or '—'} | {_moeda(c.get('valor'))} | {obj} | "
                f"{c.get('fonte') or '—'} |"
            )
        L.append("")
        L.append(f"_Total de {len(cs)} contrato(s) individual(is)._")
    else:
        L.append("_Sem contratos vinculados a este CNPJ._")
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

    # Rede societária — empresas irmãs (mesmo sócio)
    L.append("## Rede societária (empresas irmãs)")
    irmas = dados.get("irmas") or []
    if irmas:
        L.append("| Empresa | CNPJ | Valor recebido | Sócio em comum |")
        L.append("|---|---|---:|---|")
        for p in irmas:
            L.append(
                f"| {(p.get('nome') or '—')[:34]} | {p.get('cnpj')} | "
                f"{_moeda(p.get('valor'))} | {p.get('socio_comum') or '—'} |"
            )
    else:
        L.append("_Nenhuma empresa irmã (sócio em comum) entre as fornecedoras._")
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
        L.append("| Doador | CPF | Candidato | Cargo | Ano | Valor | Vínculo |")
        L.append("|---|---|---|---|---|---:|---|")
        for d in doacoes:
            L.append(
                f"| {(d.get('doador_nome') or '—')[:28]} | "
                f"{d.get('doador_cpf_mascarado') or '—'} | "
                f"{(d.get('candidato') or '—')[:24]} | {d.get('cargo') or '—'} | "
                f"{d.get('ano_eleicao') or '—'} | {_moeda(d.get('valor'))} | "
                f"{d.get('vinculo') or '—'} |"
            )
    else:
        L.append("_Nenhuma doação relacionada._")
    L.append("")

    # Fontes
    L.append("## Fontes consultadas")
    for nome_fonte, url in FONTES.items():
        L.append(f"- {nome_fonte}: {url}")
    L.append("")

    # Rodapé com metadados e aviso legal explícito.
    rodape = dados.get("rodape") or {}
    L.append("---")
    L.append(
        f"**Documento gerado em:** {rodape.get('gerado_em', '—')}  "
    )
    L.append(f"**Versão do banco:** {rodape.get('versao_banco', '—')}")
    L.append("")
    L.append(
        "> **Aviso legal.** Este documento contém indícios sujeitos a apuração. "
        "Não constitui prova de ilícito. Todas as informações têm fonte oficial "
        "identificada. Casamentos por nome/CPF parcial podem conter homônimos."
    )

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
