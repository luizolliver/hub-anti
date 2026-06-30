"""
Testes da Etapa 6 — motor de bandeiras vermelhas.

Cada regra tem um caso que claramente dispara e um que claramente não.
O agregador soma os pesos certos. Tudo offline, com entradas fabricadas.
"""

from src.analysis.flags import (
    PESOS,
    aditivo_eleva_valor,
    avaliar,
    avaliar_fornecedor,
    concentracao_fornecedor,
    concentracao_por_secretaria,
    dispensa_acima_limite,
    dispensa_inexigibilidade,
    empresa_nova_no_contrato,
    empresa_recem_aberta,
    entidade_sem_fins_sem_licitacao,
    fim_de_exercicio,
    fornecedor_ou_socio_sancionado,
    multiplos_contratos_objeto_similar,
    participante_unico,
    situacao_cadastral_irregular,
    sobrepreco_item,
    socio_multiplas_empresas_fornecedoras,
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


# ---------------------------------------------------------------------------
# Bandeiras de nível de fornecedor (Parte 2)
# ---------------------------------------------------------------------------
def test_empresa_nova_no_contrato():
    contratos = [{"data": "2024-03-10"}, {"data": "2024-09-01"}]
    b = empresa_nova_no_contrato("2024-01-05", contratos)  # 1º contrato 65 dias após abrir
    assert b and b.codigo == "EMPRESA_NOVA_NO_CONTRATO"
    assert b.evidencia["dias"] == 65
    # Empresa antiga: nada.
    assert empresa_nova_no_contrato("2010-01-01", contratos) is None
    # Sem data de abertura ou sem contratos: nada.
    assert empresa_nova_no_contrato(None, contratos) is None
    assert empresa_nova_no_contrato("2024-01-05", []) is None


def test_dispensa_acima_limite():
    contratos = [
        {"modalidade": "Pregao Eletronico", "valor": 999999, "objeto": "merenda"},
        {"modalidade": "Contratacao Direta - Dispensa de licitacao", "valor": 80000, "objeto": "papel"},
    ]
    b = dispensa_acima_limite(contratos)
    assert b and b.codigo == "DISPENSA_ACIMA_LIMITE"
    assert b.evidencia["valor"] == 80000
    assert b.evidencia["limite_vigente"] == 57208.33  # bens/serviços
    # Obra usa o limite maior: 80k não dispara.
    obra = [{"modalidade": "Dispensa", "valor": 80000, "objeto": "pavimentação da rua X"}]
    assert dispensa_acima_limite(obra) is None
    # Dispensa abaixo do limite: nada.
    assert dispensa_acima_limite([{"modalidade": "Dispensa", "valor": 1000, "objeto": "x"}]) is None


def test_entidade_sem_fins_sem_licitacao():
    contratos = [{"modalidade": "Contratacao Direta - Inexigibilidade de licitacao", "valor": 50000}]
    b = entidade_sem_fins_sem_licitacao("Associação Privada", contratos)
    assert b and b.codigo == "ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO"
    # Empresa comum (LTDA) não dispara.
    assert entidade_sem_fins_sem_licitacao("Sociedade Empresária Limitada", contratos) is None
    # Associação, mas só com pregão (com licitação): nada.
    assert entidade_sem_fins_sem_licitacao("Fundação Privada", [{"modalidade": "Pregao Presencial"}]) is None


def test_concentracao_por_secretaria():
    contratos = [
        {"orgao": "SAAE", "ano": "2021", "valor": 500},
        {"orgao": "SAAE", "ano": "2021", "valor": 300},
    ]
    totais = {("SAAE", "2021"): {"total": 1000, "n": 5}}  # 800/1000 = 80%
    b = concentracao_por_secretaria(contratos, totais)
    assert b and b.codigo == "CONCENTRACAO_POR_SECRETARIA"
    assert b.evidencia["fracao"] == 0.8
    # Grupo com menos de 3 contratos: ignorado (ruído).
    assert concentracao_por_secretaria(contratos, {("SAAE", "2021"): {"total": 1000, "n": 2}}) is None
    # Abaixo de 40%: nada.
    assert concentracao_por_secretaria(contratos, {("SAAE", "2021"): {"total": 9000, "n": 9}}) is None


def test_multiplos_contratos_objeto_similar():
    base = {"orgao": "PREFEITURA", "objeto": "AQUISICAO DE MATERIAL DE LIMPEZA E HIGIENE"}
    contratos = [
        {**base, "data": "2022-01-05"},
        {**base, "data": "2022-02-10"},
        {**base, "data": "2022-03-01"},  # 3 em ~55 dias → fracionamento
    ]
    b = multiplos_contratos_objeto_similar(contratos)
    assert b and b.codigo == "MULTIPLOS_CONTRATOS_OBJETO_SIMILAR"
    assert b.evidencia["qtde"] == 3
    # Espaçados (>90 dias entre os 3): nada.
    espacados = [
        {**base, "data": "2022-01-05"},
        {**base, "data": "2022-06-10"},
        {**base, "data": "2022-12-01"},
    ]
    assert multiplos_contratos_objeto_similar(espacados) is None


def test_socio_multiplas_empresas_fornecedoras():
    assert socio_multiplas_empresas_fornecedoras(3).codigo == "SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS"
    assert socio_multiplas_empresas_fornecedoras(2) is None
    assert socio_multiplas_empresas_fornecedoras(0) is None


def test_avaliar_fornecedor_soma_pesos():
    ctx = {
        "situacao_cadastral": "BAIXADA",
        "natureza_juridica": "Associação Privada",
        "data_inicio_atividade": "2024-01-01",
        "sancoes": None,
        "valor_pago": 1, "total_pago": 1000,
        "contratos": [
            {"modalidade": "Dispensa", "valor": 80000, "objeto": "papel sulfite A4",
             "data": "2024-02-01", "orgao": "PREFEITURA", "ano": "2024"},
        ],
        "totais_orgao_ano": {},
        "n_empresas_irmas_fornecedoras": 3,
    }
    res = avaliar_fornecedor(ctx)
    codigos = {b.codigo for b in res["bandeiras"]}
    assert {"SITUACAO_CADASTRAL", "EMPRESA_NOVA_NO_CONTRATO", "DISPENSA_ACIMA_LIMITE",
            "ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO",
            "SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS"} <= codigos
    assert res["nivel_atencao"] == sum(b.peso for b in res["bandeiras"])
