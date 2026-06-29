"""
Testes da Etapa 3 — resolução de entidades.

Validação de CNPJ/CPF, normalização de nomes, reconciliação de contratos
entre fontes e construção da tabela `fornecedores`. Tudo offline.
"""

from src.collectors.pncp import salvar_contratos
from src.collectors.tce_despesas import salvar_despesas
from src.db import init_db
from src.models import Contrato, Despesa
from src.normalize.entidades import (
    cnpj_raiz,
    cnpj_valido,
    construir_fornecedores,
    cpf_valido,
    normalizar_cnpj,
    normalizar_nome,
    reconciliar_contratos,
)

# CNPJs reais de Barretos (devem validar).
CNPJS_REAIS = [
    "44780609000104",  # Prefeitura
    "49150352000112",  # Fundação Pio XII
    "44782779000110",  # Santa Casa
]


# --- CNPJ --------------------------------------------------------------------
def test_cnpj_validos():
    for c in CNPJS_REAIS:
        assert cnpj_valido(c)


def test_cnpj_digito_errado():
    # Último dígito trocado invalida.
    assert not cnpj_valido("44780609000105")


def test_cnpj_tamanho_e_repetidos():
    assert not cnpj_valido("123")
    assert not cnpj_valido("00000000000000")


def test_normalizar_cnpj():
    assert normalizar_cnpj("44.780.609/0001-04") == "44780609000104"
    # Com zero à esquerda perdido (13 dígitos) → completa e valida.
    assert normalizar_cnpj("2558157000162") == "02558157000162"
    # Inválido → None.
    assert normalizar_cnpj("44780609000105") is None


def test_cnpj_raiz():
    # Raiz = 8 primeiros dígitos; agrupa matriz + filiais.
    assert cnpj_raiz("44.780.609/0001-04") == "44780609"
    # CNPJ inválido → sem raiz.
    assert cnpj_raiz("44780609000105") is None


# --- CPF ---------------------------------------------------------------------
def test_cpf_valido_e_invalido():
    assert cpf_valido("111.444.777-35")
    assert not cpf_valido("11144477700")
    assert not cpf_valido("00000000000")


# --- Nome --------------------------------------------------------------------
def test_normalizar_nome_equivalencia():
    a = normalizar_nome("Telefônica Brasil S.A.")
    b = normalizar_nome("TELEFONICA  BRASIL S A")
    assert a == b == "TELEFONICA BRASIL S A"


def test_normalizar_nome_vazio():
    assert normalizar_nome(None) == ""
    assert normalizar_nome("") == ""


# --- Reconciliação de contratos ---------------------------------------------
def _contrato(**kw) -> Contrato:
    base = dict(id="x", fonte="PNCP", orgao_cnpj="44780609000104", ano="2026",
                fornecedor_cnpj="49150352000112", valor=1000.0)
    base.update(kw)
    return Contrato(**base)


def test_reconciliacao_mesma_chave_vira_um():
    pncp = _contrato(id="pncp-1", fonte="PNCP", fornecedor_nome=None, objeto=None)
    tce = _contrato(id="tce-1", fonte="TCE-SP", fornecedor_nome="FUNDACAO PIO XII",
                    objeto="SERVICOS DE SAUDE")
    resultado = reconciliar_contratos([pncp, tce])
    assert len(resultado) == 1
    canonico = resultado[0]
    # Campos faltantes no PNCP foram preenchidos pelo TCE.
    assert canonico.fornecedor_nome == "FUNDACAO PIO XII"
    assert canonico.objeto == "SERVICOS DE SAUDE"
    assert set(canonico.raw["fontes"]) == {"PNCP", "TCE-SP"}
    assert set(canonico.raw["ids_origem"]) == {"pncp-1", "tce-1"}


def test_reconciliacao_chaves_diferentes_nao_mescla():
    a = _contrato(id="a", valor=1000.0)
    b = _contrato(id="b", valor=2000.0)  # valor diferente → chave diferente
    assert len(reconciliar_contratos([a, b])) == 2


# --- Tabela fornecedores -----------------------------------------------------
def test_construir_fornecedores(tmp_path):
    conn = init_db(tmp_path / "t.db")

    # Um contrato PNCP com fornecedor + duas despesas TCE do mesmo CNPJ.
    salvar_contratos(conn, [
        Contrato(id="c1", fonte="PNCP", fornecedor_cnpj="49150352000112",
                 fornecedor_nome="FUNDACAO PIO XII", valor=500.0),
    ])
    salvar_despesas(conn, [
        Despesa(id="d1", fonte="TCE-SP", fornecedor_tipo="CNPJ",
                fornecedor_documento="49150352000112",
                fornecedor_nome="FUNDACAO PIO XII", evento="Valor Pago", valor=1000.0),
        Despesa(id="d2", fonte="TCE-SP", fornecedor_tipo="CNPJ",
                fornecedor_documento="44782779000110",
                fornecedor_nome="SANTA CASA", evento="Valor Pago", valor=300.0),
        # CPF mascarado não entra em fornecedores.
        Despesa(id="d3", fonte="TCE-SP", fornecedor_tipo="CPF",
                fornecedor_documento=None, fornecedor_nome="FULANO", valor=50.0),
    ])

    n = construir_fornecedores(conn)
    assert n == 2  # dois CNPJs distintos

    pio = conn.execute(
        "SELECT * FROM fornecedores WHERE cnpj='49150352000112'"
    ).fetchone()
    assert pio["n_contratos"] == 1
    assert pio["n_despesas"] == 1
    assert pio["valor_contratos"] == 500.0
    assert pio["valor_pago"] == 1000.0
    assert pio["fontes"] == "PNCP,TCE-SP"
    assert pio["nome_chave"] == "FUNDACAO PIO XII"
    assert pio["cnpj_raiz"] == "49150352"
    conn.close()
