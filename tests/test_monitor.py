"""
Testes da Etapa 11 — monitoramento incremental.

Detecção de novidades é idempotente (2ª passada não repete) e o alerta em
Markdown reflete o que mudou. Offline.
"""

from src.db import init_db
from src.monitor import (
    detectar_contratos_novos,
    detectar_fornecedores_novos,
    gerar_alerta_md,
    verificar,
)


def _seed(tmp_path):
    conn = init_db(tmp_path / "t.db")
    # Contrato por dispensa em dezembro → 2 bandeiras (dispensa + fim de exercício).
    conn.execute(
        "INSERT INTO contratos (id, fonte, orgao, modalidade, objeto, valor, data) "
        "VALUES ('c1','PNCP','PREF','Dispensa','Compra X', 50000, '2024-12-10')"
    )
    # Contrato normal (pregão, junho) → sem bandeira de contrato.
    conn.execute(
        "INSERT INTO contratos (id, fonte, orgao, modalidade, objeto, valor, data) "
        "VALUES ('c2','PNCP','PREF','Pregão - Eletrônico','Compra Y', 100, '2024-06-10')"
    )
    # Fornecedor sancionado (entra no radar).
    conn.execute("INSERT INTO fornecedores (cnpj, nome, valor_pago) VALUES ('09095412000127','ABBC', 2264000.0)")
    conn.execute(
        "INSERT INTO sancoes_encontradas (id, alvo_tipo, alvo_cnpj, fonte, categoria, vinculo) "
        "VALUES ('s','fornecedor','09095412000127','CEIS','Impedimento','cnpj')"
    )
    conn.commit()
    return conn


def test_detecta_contrato_sinalizado(tmp_path):
    conn = _seed(tmp_path)
    novos = detectar_contratos_novos(conn)
    ids = {c["id"] for c in novos}
    assert "c1" in ids       # dispensa + dezembro
    assert "c2" not in ids   # pregão comum
    c1 = next(c for c in novos if c["id"] == "c1")
    assert "DISPENSA_INEXIGIBILIDADE" in c1["bandeiras"]
    assert "FIM_DE_EXERCICIO" in c1["bandeiras"]
    conn.close()


def test_idempotente(tmp_path):
    conn = _seed(tmp_path)
    assert detectar_contratos_novos(conn)        # 1ª passada acha
    assert detectar_contratos_novos(conn) == []  # 2ª não repete
    assert detectar_fornecedores_novos(conn)
    assert detectar_fornecedores_novos(conn) == []
    conn.close()


def test_fornecedor_sobe_de_nivel_gera_novo_alerta(tmp_path):
    conn = _seed(tmp_path)
    detectar_fornecedores_novos(conn)  # marca nível atual
    # Aumenta o nível adicionando situação cadastral irregular.
    conn.execute(
        "INSERT INTO empresas (cnpj, razao_social, situacao_cadastral) "
        "VALUES ('09095412000127','ABBC','INAPTA')"
    )
    conn.commit()
    de_novo = detectar_fornecedores_novos(conn)
    assert any(f["cnpj"] == "09095412000127" for f in de_novo)  # nível mudou → realerta
    conn.close()


def test_alerta_md_conteudo():
    md = gerar_alerta_md(
        contratos_novos=[{"id": "c1", "orgao": "PREF", "valor": 50000, "data": "2024-12-10",
                          "objeto": "X", "bandeiras": ["DISPENSA_INEXIGIBILIDADE"], "nivel": 2}],
        fornecedores_novos=[{"cnpj": "09095412000127", "nome": "ABBC", "valor_pago": 2264000.0,
                             "nivel_atencao": 9, "bandeiras": ["FORNECEDOR_SANCIONADO"]}],
        quando="2026-06-30 10:00",
    )
    assert "Alerta do Observatório" in md
    assert "ABBC" in md and "nível 9" in md
    assert "Contratos novos sinalizados" in md


def test_alerta_vazio():
    md = gerar_alerta_md([], [], quando="2026-06-30 10:00")
    assert "Nenhuma novidade" in md


def test_verificar_integra(tmp_path):
    conn = _seed(tmp_path)
    r = verificar(conn)
    assert r["contratos_novos"] and r["fornecedores_novos"]
    assert "Alerta do Observatório" in r["alerta_md"]
    conn.close()
