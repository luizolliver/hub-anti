"""Testes da Etapa 0 — garante que o banco e o schema são criados."""

import sqlite3

from src.db import init_db


def test_init_db_cria_arquivo(tmp_path):
    # Usa um banco temporário, isolado do banco real do projeto.
    db_file = tmp_path / "teste.db"
    conn = init_db(db_file)
    conn.close()
    assert db_file.exists()


def test_tabela_contratos_existe(tmp_path):
    db_file = tmp_path / "teste.db"
    conn = init_db(db_file)
    cur = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='contratos';"
    )
    assert cur.fetchone() is not None
    conn.close()


def test_contratos_tem_colunas_esperadas(tmp_path):
    db_file = tmp_path / "teste.db"
    conn = init_db(db_file)
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(contratos);")}
    esperadas = {
        "id",
        "fonte",
        "fornecedor_cnpj",
        "fornecedor_nome",
        "valor",
        "data",
        "municipio_ibge",
    }
    assert esperadas.issubset(cols)
    conn.close()


def test_dedup_por_id(tmp_path):
    # Inserir o mesmo id duas vezes (INSERT OR IGNORE) não deve duplicar.
    db_file = tmp_path / "teste.db"
    conn = init_db(db_file)
    for _ in range(2):
        conn.execute(
            "INSERT OR IGNORE INTO contratos (id, fonte) VALUES (?, ?);",
            ("contrato-1", "PNCP"),
        )
    conn.commit()
    (total,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    assert total == 1
    conn.close()


def test_init_db_idempotente(tmp_path):
    # Rodar init_db duas vezes não deve dar erro.
    db_file = tmp_path / "teste.db"
    init_db(db_file).close()
    init_db(db_file).close()
    # E continua sendo um banco SQLite válido.
    conn = sqlite3.connect(db_file)
    conn.execute("SELECT 1;")
    conn.close()
