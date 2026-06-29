"""Testes da Etapa 0 — garante que config.py carrega e tem as constantes."""

import config


def test_config_carrega_constantes_essenciais():
    # As constantes de identificação do município devem existir e não ser vazias.
    assert config.CODIGO_IBGE
    assert config.CODIGO_TCE_MUNICIPIO
    assert config.UF == "SP"


def test_ibge_barretos_correto():
    # Código IBGE de Barretos confirmado no blueprint.
    assert config.CODIGO_IBGE == "3505500"


def test_constantes_de_orgaos_existem():
    # Placeholders de CNPJ devem existir (serão preenchidos depois).
    assert hasattr(config, "CNPJ_PREFEITURA")
    assert hasattr(config, "CNPJ_CAMARA")


def test_caminhos_definidos():
    # Caminhos de dados/banco devem estar configurados.
    assert config.DATA_DIR.name == "data"
    assert str(config.DB_PATH).endswith("observatorio.db")


def test_limiares_de_analise_sao_numericos():
    assert isinstance(config.LIMIAR_EMPRESA_NOVA_MESES, int)
    assert 0 < config.LIMIAR_ADITIVO_PERCENTUAL < 1
    assert 0 < config.LIMIAR_CONCENTRACAO < 1
