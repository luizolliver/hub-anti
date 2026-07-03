"""Testes das funções puras de links para a fonte (web/sources.py)."""

from web import sources


def test_contrato_pncp_permalink():
    lk = sources.contrato_link("PNCP", "/contratos/44780609000104/2026/69")
    assert lk["tipo"] == "registro"
    # sequencial é normalizado para 6 dígitos (padrão da UI do PNCP)
    assert lk["url"] == "https://pncp.gov.br/app/contratos/44780609000104/2026/000069"


def test_contrato_pncp_id_invalido_cai_para_none():
    assert sources.contrato_link("PNCP", None) is None
    assert sources.contrato_link("PNCP", "lixo") is None


def test_contrato_tce_aponta_para_portal():
    lk = sources.contrato_link("TCE-SP", "2019900000117")
    assert lk["tipo"] == "portal"
    assert "transparencia.tce.sp.gov.br" in lk["url"]


def test_contrato_fonte_desconhecida():
    assert sources.contrato_link("OUTRA", "x") is None


def test_sancao_por_documento():
    lk = sources.sancao_link("CEIS", documento="09.095.412/0001-27")
    assert lk["tipo"] == "busca"
    # só dígitos no termo
    assert lk["url"].endswith("termo=09095412000127")
    assert "CEIS" in lk["label"]


def test_sancao_por_nome_quando_sem_documento():
    lk = sources.sancao_link("CNEP", documento=None, nome="FULANO DE TAL")
    assert lk["tipo"] == "busca"
    assert "FULANO" in lk["url"]  # nome URL-encoded


def test_sancao_sem_dados_cai_para_consulta():
    lk = sources.sancao_link("CEIS", documento=None, nome=None)
    assert lk["tipo"] == "portal"
    assert lk["url"].endswith("/sancoes/consulta")
