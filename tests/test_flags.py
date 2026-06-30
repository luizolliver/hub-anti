"""
Testes da Etapa 6 — motor de bandeiras vermelhas.

Cada regra tem um caso que claramente dispara e um que claramente não.
O agregador soma os pesos certos. Tudo offline, com entradas fabricadas.
"""

from src.analysis.flags import (
    PESOS,
    aditivo_eleva_valor,
    avaliar,
    concentracao_fornecedor,
    dispensa_inexigibilidade,
    empresa_recem_aberta,
    fim_de_exercicio,
    fornecedor_ou_socio_sancionado,
    participante_unico,
    situacao_cadastral_irregular,
    sobrepreco_item,
)


def test_dispensa():
    assert dispensa_inexigibilidade("Dispensa").codigo == "DISPENSA_INEXIGIBILIDADE"
    assert dispensa_inexigibilidade("Inexigibilidade") is not None
    assert dispensa_inexigibilidade("Pregão - Eletrônico") is None
    assert dispensa_inexigibilidade(None) is None


def test_empresa_nova():
    # Aberta 2 meses antes do contrato (< 6) → dispara.
    b = empresa_recem_aberta("2024-10-01", "2024-12-01", limiar_meses=6)
    assert b and b.codigo == "EMPRESA_NOVA"
    assert b.evidencia["idade_meses"] == 2
    # Empresa antiga → não dispara.
    assert empresa_recem_aberta("2000-01-01", "2024-12-01", limiar_meses=6) is None
    # Sem data → não dispara.
    assert empresa_recem_aberta(None, "2024-12-01") is None


def test_fornecedor_sancionado():
    sancoes = [{"fonte": "CEIS", "categoria": "Suspensão", "nome_sancionado": "X", "vinculo": "cnpj"}]
    b = fornecedor_ou_socio_sancionado(sancoes)
    assert b and b.codigo == "FORNECEDOR_SANCIONADO"
    assert b.evidencia["fontes"] == ["CEIS"]
    assert fornecedor_ou_socio_sancionado([]) is None
    assert fornecedor_ou_socio_sancionado(None) is None


def test_situacao_cadastral():
    assert situacao_cadastral_irregular("BAIXADA") is not None
    assert situacao_cadastral_irregular("INAPTA") is not None
    # ATIVA mas com situação especial (ex.: INTERVENCAO) → dispara.
    assert situacao_cadastral_irregular("ATIVA", "INTERVENCAO") is not None
    # ATIVA e sem especial → não dispara.
    assert situacao_cadastral_irregular("ATIVA", "") is None
    assert situacao_cadastral_irregular(None) is None


def test_participante_unico():
    assert participante_unico(1) is not None
    assert participante_unico(3) is None
    assert participante_unico(None) is None


def test_concentracao():
    assert concentracao_fornecedor(60, 100, limiar_fracao=0.5) is not None
    assert concentracao_fornecedor(40, 100, limiar_fracao=0.5) is None
    assert concentracao_fornecedor(10, 0) is None
    assert concentracao_fornecedor(None, 100) is None


def test_aditivo():
    # 100k → 200k = +100% (≥25%) → dispara.
    b = aditivo_eleva_valor(100000, 200000, limiar_pct=0.25)
    assert b and b.codigo == "ADITIVO_ELEVADO"
    # +10% → não dispara.
    assert aditivo_eleva_valor(100000, 110000, limiar_pct=0.25) is None
    assert aditivo_eleva_valor(0, 100) is None


def test_sobrepreco():
    assert sobrepreco_item(10, 2, fator=2.0) is not None  # 5x
    assert sobrepreco_item(3, 2, fator=2.0) is None        # 1.5x
    assert sobrepreco_item(10, 0) is None


def test_fim_de_exercicio():
    assert fim_de_exercicio("2024-12-10") is not None
    assert fim_de_exercicio("2024-06-10") is None
    assert fim_de_exercicio(None) is None


# --- Agregador ---------------------------------------------------------------
def test_avaliar_soma_pesos():
    contrato = {"modalidade": "Dispensa", "data": "2024-12-10", "valor": 200000}
    contexto = {
        "data_inicio_atividade": "2024-10-01",  # ~2 meses → empresa nova
        "sancoes": [{"fonte": "CEIS", "categoria": "Suspensão"}],
        "situacao_cadastral": "INAPTA",
        "num_participantes": 1,
        "valor_fornecedor": 60,
        "valor_total": 100,            # 60% → concentração
        "valor_original": 100000,      # → 100% aditivo
        "preco_unitario": 10,
        "mediana_item": 2,             # 5x → sobrepreço
    }
    resultado = avaliar(contrato, contexto)
    codigos = {b.codigo for b in resultado["bandeiras"]}
    esperado = {
        "DISPENSA_INEXIGIBILIDADE", "EMPRESA_NOVA", "FORNECEDOR_SANCIONADO",
        "SITUACAO_CADASTRAL", "PARTICIPANTE_UNICO", "CONCENTRACAO",
        "ADITIVO_ELEVADO", "SOBREPRECO", "FIM_DE_EXERCICIO",
    }
    assert codigos == esperado
    assert resultado["nivel_atencao"] == sum(PESOS[c] for c in esperado)


def test_avaliar_contrato_limpo():
    contrato = {"modalidade": "Pregão - Eletrônico", "data": "2024-06-10", "valor": 1000}
    resultado = avaliar(contrato, {})
    assert resultado["bandeiras"] == []
    assert resultado["nivel_atencao"] == 0
