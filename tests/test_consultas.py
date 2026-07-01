"""Testes da Etapa 10 — funções de consulta do painel (sem UI)."""

from src.consultas import (
    buscar_fornecedores,
    buscar_pessoas,
    metricas_gerais,
    ranking_atencao,
)
from src.db import init_db


def _seed(tmp_path):
    conn = init_db(tmp_path / "t.db")
    conn.executemany(
        "INSERT INTO fornecedores (cnpj, nome, valor_pago) VALUES (?,?,?)",
        [
            ("09095412000127", "ABBC", 2264000.0),       # inapta + sancionada
            ("44782779000110", "SANTA CASA", 9876208.0),  # intervenção + concentração
            ("00000000000191", "EMPRESA LIMPA", 100.0),   # sem bandeira
        ],
    )
    conn.executemany(
        "INSERT INTO empresas (cnpj, razao_social, situacao_cadastral, situacao_especial) VALUES (?,?,?,?)",
        [
            ("09095412000127", "ABBC", "INAPTA", None),
            ("44782779000110", "SANTA CASA", "ATIVA", "INTERVENCAO"),
            ("00000000000191", "EMPRESA LIMPA", "ATIVA", None),
        ],
    )
    conn.execute(
        "INSERT INTO sancoes_encontradas (id, alvo_tipo, alvo_cnpj, fonte, categoria, vinculo) "
        "VALUES ('s','fornecedor','09095412000127','CEIS','Impedimento','cnpj')"
    )
    conn.execute(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio) VALUES ('x','09095412000127','HENRIQUE DUARTE PRATA')"
    )
    conn.commit()
    return conn


def test_metricas(tmp_path):
    conn = _seed(tmp_path)
    m = metricas_gerais(conn)
    assert m["fornecedores"] == 3
    assert m["empresas_enriquecidas"] == 3
    assert m["sancoes"] == 1
    assert m["total_pago"] > 0
    conn.close()


def test_ranking_ordena_por_atencao(tmp_path):
    conn = _seed(tmp_path)
    rank = ranking_atencao(conn, limite=10)
    # ABBC (situação + sanção) deve estar à frente; empresa limpa não entra.
    cnpjs = [r["cnpj"] for r in rank]
    assert "09095412000127" in cnpjs
    assert "44782779000110" in cnpjs
    assert "00000000000191" not in cnpjs
    # Ordenado desc por nível.
    niveis = [r["nivel_atencao"] for r in rank]
    assert niveis == sorted(niveis, reverse=True)
    # ABBC tem situação(4) + sanção(5) = 9.
    abbc = next(r for r in rank if r["cnpj"] == "09095412000127")
    assert abbc["nivel_atencao"] == 9
    conn.close()


def test_buscar_fornecedores(tmp_path):
    conn = _seed(tmp_path)
    assert buscar_fornecedores(conn, "SANTA")[0]["cnpj"] == "44782779000110"
    assert buscar_fornecedores(conn, "09095412")[0]["nome"] == "ABBC"
    assert buscar_fornecedores(conn, "") == []
    conn.close()


def test_buscar_pessoas(tmp_path):
    conn = _seed(tmp_path)
    res = buscar_pessoas(conn, "HENRIQUE")
    assert res and res[0]["cnpj_empresa"] == "09095412000127"
    conn.close()


def _seed_rede(tmp_path):
    """Dois fornecedores com o MESMO sócio (nome+CPF visível) e contratos."""
    conn = init_db(tmp_path / "r.db")
    conn.executemany(
        "INSERT INTO fornecedores (cnpj, nome, valor_pago, valor_contratos) VALUES (?,?,?,?)",
        [
            ("11111111000111", "ALFA CONSTRUCOES", 0.0, 500000.0),
            ("22222222000122", "BETA ENGENHARIA", 0.0, 300000.0),
            ("33333333000133", "GAMA SERVICOS", 0.0, 100.0),
        ],
    )
    # Mesmo sócio (chave nome + 6 díg.) nas duas primeiras.
    conn.executemany(
        "INSERT INTO socios (id, cnpj_empresa, nome_socio, nome_socio_chave, documento_visivel, tipo_socio) "
        "VALUES (?,?,?,?,?,?)",
        [
            ("a", "11111111000111", "JOAO DA SILVA", "JOAO DA SILVA", "234078", "PF"),
            ("b", "22222222000122", "JOAO DA SILVA", "JOAO DA SILVA", "234078", "PF"),
            ("c", "33333333000133", "MARIA SOUZA", "MARIA SOUZA", "999999", "PF"),
        ],
    )
    conn.executemany(
        "INSERT INTO contratos (id, fonte, fornecedor_cnpj, orgao, modalidade, objeto, valor, data, ano) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        [
            ("c1", "TCE-SP", "11111111000111", "PREFEITURA",
             "Contratacao Direta - Dispensa de licitacao", "PAVIMENTACAO DA AVENIDA X",
             90000.0, "2021-03-01", "2021"),
        ],
    )
    conn.commit()
    return conn


def test_empresas_irmas(tmp_path):
    from src.consultas import empresas_irmas
    conn = _seed_rede(tmp_path)
    irmas = empresas_irmas(conn, "11111111000111")
    assert [i["cnpj"] for i in irmas] == ["22222222000122"]
    assert irmas[0]["socio_comum"] == "JOAO DA SILVA"
    # Quem não compartilha sócio não tem irmãs.
    assert empresas_irmas(conn, "33333333000133") == []
    conn.close()


def test_buscar_socios_por_nome(tmp_path):
    from src.consultas import buscar_socios
    conn = _seed_rede(tmp_path)
    res = buscar_socios(conn, "JOAO")
    assert len(res) == 1
    pessoa = res[0]
    assert {e["cnpj"] for e in pessoa["empresas"]} == {"11111111000111", "22222222000122"}
    assert pessoa["total"] == 800000.0
    conn.close()


def test_buscar_por_objeto(tmp_path):
    from src.consultas import buscar_por_objeto
    conn = _seed_rede(tmp_path)
    res = buscar_por_objeto(conn, "pavimenta")
    assert res and res[0]["fornecedor_cnpj"] == "11111111000111"
    assert buscar_por_objeto(conn, "inexistente") == []
    conn.close()


def test_ranking_inclui_flags_novas(tmp_path):
    conn = _seed_rede(tmp_path)
    # Alfa abriu < 1 ano antes do contrato (2021-03-01) → EMPRESA_NOVA_NO_CONTRATO.
    conn.execute(
        "INSERT INTO empresas (cnpj, razao_social, situacao_cadastral, data_inicio_atividade) "
        "VALUES ('11111111000111','ALFA','ATIVA','2020-10-01')"
    )
    conn.commit()
    rank = ranking_atencao(conn, limite=10)
    alfa = next(r for r in rank if r["cnpj"] == "11111111000111")
    assert "EMPRESA_NOVA_NO_CONTRATO" in alfa["bandeiras"]
    # Só 2 empresas com o sócio em comum → a bandeira de sócio NÃO dispara.
    assert "SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS" not in alfa["bandeiras"]
    # valor_total = pago (0) + contratado (500k) — não exibe R$ 0 enganoso.
    assert alfa["valor_pago"] == 0
    assert alfa["valor_total"] == 500000.0
    conn.close()


def test_cnpjs_por_filtro(tmp_path):
    from src.consultas import cnpjs_por_filtro
    conn = _seed_rede(tmp_path)
    # Sem filtro ativo → None (sem restrição).
    assert cnpjs_por_filtro(conn, None) is None
    assert cnpjs_por_filtro(conn, {"orgao": None, "valor_min": 0}) is None
    # Órgão com contrato só do ALFA.
    assert cnpjs_por_filtro(conn, {"orgao": "PREFEITURA"}) == {"11111111000111"}
    # Valor mínimo acima do contrato → conjunto vazio.
    assert cnpjs_por_filtro(conn, {"valor_min": 1_000_000}) == set()
    conn.close()


def test_ranking_com_filtro(tmp_path):
    conn = _seed_rede(tmp_path)
    conn.execute(
        "INSERT INTO empresas (cnpj, razao_social, situacao_cadastral, data_inicio_atividade) "
        "VALUES ('11111111000111','ALFA','ATIVA','2020-10-01')"  # EMPRESA_NOVA_NO_CONTRATO
    )
    conn.commit()
    # Filtro casa o contrato do ALFA → ALFA aparece.
    r1 = ranking_atencao(conn, filtros={"orgao": "PREFEITURA"})
    assert "11111111000111" in [x["cnpj"] for x in r1]
    # Filtro por órgão sem contrato do ALFA → ALFA some (nível segue do histórico).
    r2 = ranking_atencao(conn, filtros={"orgao": "SAAE"})
    assert "11111111000111" not in [x["cnpj"] for x in r2]
    conn.close()


def test_buscar_fornecedores_com_filtro(tmp_path):
    conn = _seed_rede(tmp_path)
    # Sem filtro acha ALFA pelo nome.
    assert buscar_fornecedores(conn, "ALFA")[0]["cnpj"] == "11111111000111"
    # Com filtro casando o contrato do ALFA, continua achando.
    assert buscar_fornecedores(conn, "ALFA", filtros={"orgao": "PREFEITURA"})
    # Com filtro que não casa, some.
    assert buscar_fornecedores(conn, "ALFA", filtros={"orgao": "SAAE"}) == []
    conn.close()
