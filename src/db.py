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
    -- Órgão público contratante (nome).
    orgao           TEXT,
    -- CNPJ do órgão contratante (apenas dígitos).
    orgao_cnpj      TEXT,
    -- Objeto/descrição do contrato.
    objeto          TEXT,
    -- Modalidade da licitação (pregão, dispensa, inexigibilidade...).
    modalidade      TEXT,
    -- CNPJ do fornecedor (apenas dígitos). Pode ser nulo até o enriquecimento.
    fornecedor_cnpj TEXT,
    -- Razão social / nome do fornecedor.
    fornecedor_nome TEXT,
    -- Valor do contrato em reais.
    valor           REAL,
    -- Data de assinatura no formato ISO (AAAA-MM-DD).
    data            TEXT,
    -- Ano do contrato.
    ano             TEXT,
    -- Código IBGE do município (filtro de Barretos).
    municipio_ibge  TEXT,
    -- Nome do município e UF (conferência).
    municipio_nome  TEXT,
    uf              TEXT,
    -- JSON bruto da fonte, para auditoria e reprocessamento.
    raw             TEXT,
    -- Carimbo de quando a linha foi inserida.
    coletado_em     TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS despesas (
    -- Identificador sintético (hash do conteúdo da linha) p/ deduplicação.
    id                    TEXT PRIMARY KEY,
    fonte                 TEXT NOT NULL,        -- sempre 'TCE-SP'
    municipio             TEXT,                 -- slug do município (ex.: 'barretos')
    -- Órgão da despesa (Prefeitura, Câmara, IPM, SAAE...).
    orgao                 TEXT,
    ano                   TEXT,
    mes                   TEXT,
    -- Estágio da despesa: Empenhado / Valor Liquidado / Valor Pago / Anulação / Reforço.
    evento                TEXT,
    nr_empenho            TEXT,
    -- CNPJ do fornecedor (apenas dígitos) quando o tipo é CNPJ; senão NULL.
    fornecedor_documento  TEXT,
    -- Classificação: 'CNPJ', 'CPF' (mascarado pelo TCE) ou 'OUTRO'.
    fornecedor_tipo       TEXT,
    fornecedor_nome       TEXT,
    -- Data de emissão da despesa em ISO (AAAA-MM-DD).
    data                  TEXT,
    valor                 REAL,
    raw                   TEXT,
    coletado_em           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fornecedores (
    -- CNPJ normalizado e validado (14 dígitos) — chave única (estabelecimento).
    cnpj             TEXT PRIMARY KEY,
    -- Raiz do CNPJ (8 dígitos): agrupa matriz + filiais (a mesma empresa).
    cnpj_raiz        TEXT,
    nome             TEXT,            -- nome canônico escolhido
    nome_chave       TEXT,            -- normalizar_nome(nome), p/ casamento
    n_contratos      INTEGER DEFAULT 0,   -- referências em contratos (PNCP)
    n_despesas       INTEGER DEFAULT 0,   -- referências em despesas (TCE)
    valor_contratos  REAL DEFAULT 0,      -- soma dos contratos
    valor_pago       REAL DEFAULT 0,      -- soma das despesas 'Valor Pago'
    fontes           TEXT,                -- ex.: 'PNCP,TCE-SP'
    atualizado_em    TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS empresas (
    cnpj                    TEXT PRIMARY KEY,
    cnpj_raiz               TEXT,
    razao_social            TEXT,
    nome_fantasia           TEXT,
    situacao_cadastral      TEXT,        -- ATIVA / BAIXADA / ...
    data_situacao_cadastral TEXT,
    situacao_especial       TEXT,        -- ex.: INTERVENCAO
    -- Data de abertura: base para "idade da empresa na data do contrato".
    data_inicio_atividade   TEXT,
    natureza_juridica       TEXT,
    porte                   TEXT,
    capital_social          REAL,
    cnae                    TEXT,
    cnae_descricao          TEXT,
    municipio               TEXT,
    uf                      TEXT,
    matriz_filial           TEXT,        -- MATRIZ / FILIAL
    raw                     TEXT,
    atualizado_em           TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS socios (
    id                TEXT PRIMARY KEY,   -- hash sintético
    cnpj_empresa      TEXT NOT NULL,
    nome_socio        TEXT,
    nome_socio_chave  TEXT,               -- normalizar_nome, p/ casamento por nome
    documento_socio   TEXT,               -- CPF vem MASCARADO pela RFB
    documento_visivel TEXT,               -- 6 dígitos visíveis do CPF (chave parcial)
    cnpj_socio        TEXT,               -- quando o sócio é PJ (CNPJ válido)
    tipo_socio        TEXT,               -- PF / PJ / OUTRO
    qualificacao      TEXT,
    data_entrada      TEXT,
    faixa_etaria      TEXT,
    raw               TEXT
);

-- Apenas os CRUZAMENTOS encontrados (não o cadastro inteiro de sanções).
CREATE TABLE IF NOT EXISTS sancoes_encontradas (
    id                   TEXT PRIMARY KEY,  -- hash sintético
    -- O que casou: 'fornecedor', 'socio_pj' (CNPJ) ou 'socio_pf' (CPF núcleo+nome).
    alvo_tipo            TEXT,
    alvo_cnpj            TEXT,   -- CNPJ do fornecedor ou da empresa do sócio
    alvo_nome            TEXT,
    -- Confiança do vínculo: 'cnpj' (exato) / 'forte' / 'investigar' / 'provavel'.
    vinculo              TEXT,
    fonte                TEXT,   -- CEIS / CNEP
    documento_sancionado TEXT,
    nome_sancionado      TEXT,
    categoria            TEXT,
    data_inicio          TEXT,
    data_fim             TEXT,
    orgao_sancionador    TEXT,
    abrangencia          TEXT,
    fundamentacao        TEXT,
    raw                  TEXT,
    encontrado_em        TEXT DEFAULT (datetime('now'))
);

-- Doações de campanha que se ligam a fornecedores/sócios de Barretos.
CREATE TABLE IF NOT EXISTS doacoes_relacionadas (
    id                TEXT PRIMARY KEY,  -- hash sintético
    -- 'socio' (sócio PF doou) ou 'fornecedor' (empresa doou — raro pós-2015).
    alvo_tipo         TEXT,
    alvo_cnpj         TEXT,   -- empresa do sócio, ou o fornecedor doador
    alvo_nome         TEXT,
    vinculo           TEXT,   -- 'forte' / 'investigar' (sócio) / 'cnpj' (empresa)
    doador_documento  TEXT,
    doador_nome       TEXT,
    -- Donatário (candidato de Barretos que recebeu a doação).
    candidato         TEXT,
    cargo             TEXT,
    partido           TEXT,
    municipio         TEXT,
    ano_eleicao       TEXT,
    valor             REAL,
    data              TEXT,
    raw               TEXT,
    encontrado_em     TEXT DEFAULT (datetime('now'))
);

-- Estado do monitor: o que já foi alertado, para não repetir.
CREATE TABLE IF NOT EXISTS monitor_estado (
    chave     TEXT PRIMARY KEY,   -- ex.: 'contrato:<id>' ou 'fornecedor:<cnpj>:<nivel>'
    tipo      TEXT,
    visto_em  TEXT DEFAULT (datetime('now'))
);

"""


# Índices criados DEPOIS da migração de colunas (podem referenciar colunas que
# só passam a existir após o ALTER TABLE de bancos antigos).
INDEXES_SQL = """
CREATE INDEX IF NOT EXISTS idx_contratos_cnpj ON contratos (fornecedor_cnpj);
CREATE INDEX IF NOT EXISTS idx_contratos_fonte ON contratos (fonte);
CREATE INDEX IF NOT EXISTS idx_despesas_forn ON despesas (fornecedor_documento);
CREATE INDEX IF NOT EXISTS idx_despesas_evento ON despesas (evento);
CREATE INDEX IF NOT EXISTS idx_fornecedores_nome ON fornecedores (nome_chave);
CREATE INDEX IF NOT EXISTS idx_fornecedores_raiz ON fornecedores (cnpj_raiz);
CREATE INDEX IF NOT EXISTS idx_empresas_raiz ON empresas (cnpj_raiz);
CREATE INDEX IF NOT EXISTS idx_socios_empresa ON socios (cnpj_empresa);
CREATE INDEX IF NOT EXISTS idx_socios_nome ON socios (nome_socio_chave);
CREATE INDEX IF NOT EXISTS idx_socios_cnpj ON socios (cnpj_socio);
CREATE INDEX IF NOT EXISTS idx_socios_visivel ON socios (documento_visivel);
CREATE INDEX IF NOT EXISTS idx_sancoes_alvo ON sancoes_encontradas (alvo_cnpj);
CREATE INDEX IF NOT EXISTS idx_doacoes_alvo ON doacoes_relacionadas (alvo_cnpj);
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


# Colunas esperadas por tabela (para migrar bancos criados por versões antigas).
# Mapeia tabela -> {coluna: tipo}. Só colunas que podem faltar em bancos velhos.
_COLUNAS_ESPERADAS = {
    "contratos": {
        "id": "TEXT", "fonte": "TEXT", "id_origem": "TEXT", "orgao": "TEXT",
        "orgao_cnpj": "TEXT", "objeto": "TEXT", "modalidade": "TEXT",
        "fornecedor_cnpj": "TEXT", "fornecedor_nome": "TEXT", "valor": "REAL",
        "data": "TEXT", "ano": "TEXT", "municipio_ibge": "TEXT",
        "municipio_nome": "TEXT", "uf": "TEXT", "raw": "TEXT", "coletado_em": "TEXT",
    },
    "fornecedores": {"cnpj_raiz": "TEXT"},
    "socios": {"documento_visivel": "TEXT"},
}


def _migrar(conn: sqlite3.Connection) -> None:
    """Adiciona colunas que faltam em bancos criados por versões anteriores."""
    for tabela, colunas in _COLUNAS_ESPERADAS.items():
        existentes = {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela});")}
        if not existentes:
            continue  # tabela ainda não existe; o CREATE já cuidou do schema novo
        for col, tipo in colunas.items():
            if col not in existentes:
                conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {col} {tipo};")


def init_db(db_path: Path | str | None = None) -> sqlite3.Connection:
    """
    Cria o schema do banco (se ainda não existir) e devolve a conexão aberta.

    É seguro chamar repetidamente: todos os CREATEs usam IF NOT EXISTS e, em
    bancos antigos, as colunas que faltam são adicionadas via migração leve.
    """
    conn = get_connection(db_path)
    conn.executescript(SCHEMA_SQL)  # cria tabelas (IF NOT EXISTS)
    _migrar(conn)                   # adiciona colunas que faltam em bancos antigos
    conn.executescript(INDEXES_SQL)  # índices, já com as colunas garantidas
    conn.commit()
    return conn


def main() -> None:
    """Ponto de entrada de linha de comando: cria o banco e avisa onde ficou."""
    conn = init_db()
    conn.close()
    print(f"Banco criado/atualizado em: {config.DB_PATH}")


if __name__ == "__main__":
    main()
