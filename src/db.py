"""
Camada de banco de dados do Observatório.

Responsável por:
  - abrir conexões SQLite;
  - criar o schema (tabelas) quando ele ainda não existe.

Nesta Etapa 0 criamos apenas a tabela mínima `contratos`. As demais
tabelas (fornecedores, empresas, socios, despesas, sancoes...) serão
adicionadas nas etapas seguintes, sempre com `CREATE TABLE IF NOT EXISTS`.

Uso pela linha de comando:
    python -m src.db        # cria data/observatorio.db com o schema atual
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import config


# SQL de criação do schema. Cada bloco é idempotente (IF NOT EXISTS),
# então rodar isto várias vezes é seguro.
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS contratos (
    -- Identificador canônico do contrato (chave de deduplicação).
    id              TEXT PRIMARY KEY,
    -- De onde veio o registro: 'PNCP' ou 'TCE-SP'.
    fonte           TEXT NOT NULL,
    -- Identificador original do contrato na fonte (antes da reconciliação).
    id_origem       TEXT,
    -- Órgão público contratante.
    orgao           TEXT,
    -- Objeto/descrição do contrato.
    objeto          TEXT,
    -- Modalidade da licitação (pregão, dispensa, inexigibilidade...).
    modalidade      TEXT,
    -- CNPJ do fornecedor (apenas dígitos).
    fornecedor_cnpj TEXT,
    -- Razão social / nome do fornecedor.
    fornecedor_nome TEXT,
    -- Valor do contrato em reais.
    valor           REAL,
    -- Data de assinatura/publicação no formato ISO (AAAA-MM-DD).
    data            TEXT,
    -- Código IBGE do município (filtro de Barretos).
    municipio_ibge  TEXT,
    -- JSON bruto da fonte, para auditoria e reprocessamento.
    raw             TEXT,
    -- Carimbo de quando a linha foi inserida.
    coletado_em     TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_contratos_cnpj ON contratos (fornecedor_cnpj);
CREATE INDEX IF NOT EXISTS idx_contratos_fonte ON contratos (fonte);
"""


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """
    Abre (e retorna) uma conexão SQLite.

    - Garante que a pasta do banco exista.
    - Ativa chaves estrangeiras e o modo de linha como dicionário (Row),
      o que facilita ler colunas pelo nome.

    Passe `db_path` para usar um banco alternativo (útil nos testes, que
    usam um arquivo temporário). Sem argumento, usa `config.DB_PATH`.
    """
    path = Path(db_path) if db_path is not None else config.DB_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """
    Cria o schema do banco (se ainda não existir) e devolve a conexão aberta.

    É seguro chamar repetidamente: todos os CREATEs usam IF NOT EXISTS.
    """
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)
    conn.commit()
    return conn


def main() -> None:
    """Ponto de entrada de linha de comando: cria o banco e avisa onde ficou."""
    conn = init_db()
    conn.close()
    print(f"Banco criado/atualizado em: {config.DB_PATH}")


if __name__ == "__main__":
    main()
