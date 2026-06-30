"""
Testes da Etapa 9 — dossiês.

`gerar_markdown` é função pura sobre o dict de dados: testamos um caso completo
(todas as seções presentes) e um caso com dados faltando (não quebra).
`montar_dossie` é testado sobre um banco-fixture pequeno.
"""

from src.db import init_db
from src.models import Bandeira
from src.reports.dossie import gerar_html, gerar_markdown, montar_dossie

SECOES = [
    "## Bandeiras",
    "## Empresa",
    "## Dinheiro recebido",
    "## Contratos",
    "## Sócios",
    "## Rede societária",
    "## Sanções",
    "## Doações",
    "## Fontes",
]


def _dados_completos() -> dict:
    return {
        "cnpj": "09095412000127",
        "empresa": {
            "razao_social": "ABBC", "situacao_cadastral": "INAPTA",
            "situacao_especial": None, "data_inicio_atividade": "2007-09-26",
            "natureza_juridica": "Associação", "porte": "DEMAIS",
            "municipio": "BARRETOS", "uf": "SP",
        },
        "fornecedor": {"nome": "ABBC", "valor_pago": 2264000.0},
        "despesas_por_evento": [{"evento": "Valor Pago", "n": 10, "soma": 2264000.0}],
        "contratos": [{"data": "2024-01-10", "modalidade": "Dispensa", "valor": 1000.0, "objeto": "X"}],
        "socios": [{"nome_socio": "FULANO", "qualificacao": "Diretor", "tipo_socio": "PF"}],
        "sancoes": [{"fonte": "CEIS", "categoria": "Impedimento", "vinculo": "cnpj",
                     "data_inicio": "2023-01-01", "data_fim": "2025-01-01",
                     "orgao_sancionador": "X"}],
        "doacoes": [{"doador_nome": "FULANO", "candidato": "BELTRANO", "cargo": "Vereador",
                     "partido": "XX", "valor": 1000.0, "data": "2024-09-01", "vinculo": "forte"}],
        "rede": [{"nivel": "forte", "outro_nome": "OUTRA", "outro_cnpj": "1", "elo": "FULANO"}],
        "bandeiras": [Bandeira(codigo="SITUACAO_CADASTRAL", descricao="INAPTA", peso=4)],
        "nivel_atencao": 4,
    }


def test_markdown_tem_todas_as_secoes():
    md = gerar_markdown(_dados_completos())
    for secao in SECOES:
        assert secao in md
    assert "indícios" in md.lower()  # aviso presente
    assert "09095412000127" in md


def test_markdown_nao_quebra_sem_dados():
    minimo = {"cnpj": "00000000000000", "empresa": None, "fornecedor": None,
              "despesas_por_evento": [], "contratos": [], "socios": [],
              "sancoes": [], "doacoes": [], "rede": [], "bandeiras": [], "nivel_atencao": 0}
    md = gerar_markdown(minimo)
    for secao in SECOES:
        assert secao in md
    assert "Nenhuma bandeira" in md


def test_gerar_html_nao_vazio():
    html = gerar_html(gerar_markdown(_dados_completos()))
    assert html.startswith("<!doctype html>")
    assert "<h1>" in html and "<table>" in html


def test_montar_dossie_do_banco(tmp_path):
    conn = init_db(tmp_path / "t.db")
    cnpj = "09095412000127"
    conn.execute("INSERT INTO empresas (cnpj, razao_social, situacao_cadastral) VALUES (?,?,?)",
                 (cnpj, "ABBC", "INAPTA"))
    conn.execute("INSERT INTO fornecedores (cnpj, nome, valor_pago) VALUES (?,?,?)",
                 (cnpj, "ABBC", 2264000.0))
    conn.execute(
        "INSERT INTO despesas (id, fonte, fornecedor_documento, fornecedor_tipo, evento, valor) "
        "VALUES ('d1','TCE-SP',?,'CNPJ','Valor Pago', 2264000.0)", (cnpj,))
    conn.execute(
        "INSERT INTO sancoes_encontradas (id, alvo_tipo, alvo_cnpj, fonte, categoria, vinculo) "
        "VALUES ('x','fornecedor',?,'CEIS','Impedimento','cnpj')", (cnpj,))
    conn.commit()

    dados = montar_dossie(conn, cnpj)
    assert dados["empresa"]["situacao_cadastral"] == "INAPTA"
    assert dados["sancoes"]
    codigos = {b.codigo for b in dados["bandeiras"]}
    assert "SITUACAO_CADASTRAL" in codigos
    assert "FORNECEDOR_SANCIONADO" in codigos
    assert dados["nivel_atencao"] > 0
    conn.close()
