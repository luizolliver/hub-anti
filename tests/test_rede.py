"""
Testes da Etapa 7 — rede societária.

Grafo pequeno e conhecido: detecção de sócio em comum (com o nível certo) e
de cluster. Offline.
"""

from src.analysis.rede import (
    clusters,
    construir_grafo,
    pares_socio_em_comum,
)


def _socio(cnpj_empresa, nome, visivel=None, tipo="PF", cnpj_socio=None):
    return {
        "cnpj_empresa": cnpj_empresa,
        "nome_socio": nome,
        "nome_socio_chave": None,  # deixa o construtor normalizar
        "documento_visivel": visivel,
        "tipo_socio": tipo,
        "cnpj_socio": cnpj_socio,
        "qualificacao": "Sócio",
    }


A, B, C, D = "11111111000111", "22222222000122", "33333333000133", "44444444000144"


def test_socio_em_comum_forte():
    # João Silva (dígitos 111111) é sócio de A e B → vínculo forte.
    socios = [
        _socio(A, "João Silva", "111111"),
        _socio(B, "JOAO SILVA", "111111"),
        _socio(C, "Maria Souza", "999999"),
    ]
    g = construir_grafo(socios)
    pares = pares_socio_em_comum(g)
    assert len(pares) == 1
    p = pares[0]
    assert {p["empresa_a"], p["empresa_b"]} == {A, B}
    assert p["nivel"] == "forte"


def test_homonimo_com_digitos_diferentes_nao_liga():
    # Mesmo nome, dígitos diferentes → pessoas diferentes → sem par.
    socios = [
        _socio(A, "João Silva", "111111"),
        _socio(D, "João Silva", "222222"),
    ]
    g = construir_grafo(socios)
    assert pares_socio_em_comum(g) == []


def test_cluster_detectado():
    # A-B ligadas por João; C isolada.
    socios = [
        _socio(A, "João Silva", "111111"),
        _socio(B, "JOAO SILVA", "111111"),
        _socio(C, "Maria Souza", "999999"),
    ]
    g = construir_grafo(socios)
    grupos = clusters(g, min_empresas=2)
    assert grupos == [[A, B]]


def test_socio_pj_liga_empresas():
    # Uma empresa-mãe (cnpj_socio) é sócia de C e D → liga empresa↔empresa.
    mae = "90000000000190"
    socios = [
        _socio(C, "HOLDING X", tipo="PJ", cnpj_socio=mae),
        _socio(D, "HOLDING X", tipo="PJ", cnpj_socio=mae),
    ]
    g = construir_grafo(socios)
    pares = pares_socio_em_comum(g)
    assert any({p["empresa_a"], p["empresa_b"]} == {C, D} and p["nivel"] == "cnpj" for p in pares)
    # C, D e a mãe formam um cluster.
    grupos = clusters(g, min_empresas=2)
    assert any(C in grupo and D in grupo for grupo in grupos)


def test_exportar_html(tmp_path):
    socios = [_socio(A, "João Silva", "111111"), _socio(B, "JOAO SILVA", "111111")]
    g = construir_grafo(socios, empresas={A: "EMPRESA A", B: "EMPRESA B"})
    from src.analysis.rede import exportar_html

    destino = tmp_path / "rede.html"
    exportar_html(g, str(destino))
    assert destino.exists() and destino.stat().st_size > 0
