"""
Configuração central do Observatório de Contratações Públicas — Barretos/SP.

Reúne todas as constantes do projeto num só lugar: códigos do município,
CNPJs dos órgãos públicos, caminhos de arquivos e limiares de análise.
Nenhuma lógica de negócio mora aqui — apenas valores que os coletores e
o motor de análise vão consultar.
"""

from pathlib import Path

# ---------------------------------------------------------------------------
# Caminhos do projeto
# ---------------------------------------------------------------------------
# Raiz do projeto = pasta onde este arquivo está.
BASE_DIR = Path(__file__).resolve().parent

# Pasta onde fica o banco SQLite e os dumps brutos (está no .gitignore).
DATA_DIR = BASE_DIR / "data"

# Caminho do banco SQLite principal.
DB_PATH = DATA_DIR / "observatorio.db"


# ---------------------------------------------------------------------------
# Identificação do município (Barretos/SP)
# ---------------------------------------------------------------------------
# Código IBGE de Barretos — confirmado no blueprint (Apêndice A).
# Usado como filtro principal nas consultas ao PNCP.
CODIGO_IBGE = "3505500"

# Como Barretos aparece DENTRO dos CSVs do TCE-SP (a confirmar na Etapa 2).
# Provavelmente o nome "BARRETOS"; pode também ser um código de município do TCE.
# PLACEHOLDER — confirmar ao inspecionar os arquivos reais do TCE-SP.
CODIGO_TCE_MUNICIPIO = "BARRETOS"

# Unidade da Federação.
UF = "SP"

# ID interno do município de Barretos no índice de busca do PNCP
# (a search API filtra por este id, NÃO pelo código IBGE). Confirmado em jun/2026.
PNCP_MUNICIPIO_ID = "3330"


# ---------------------------------------------------------------------------
# Endpoints do PNCP
# ---------------------------------------------------------------------------
# Search API (backend do site pncp.gov.br) — rápida, filtra por municipio_id,
# traz a maioria dos campos do contrato (valor, modalidade, objeto, órgão, datas)
# mas NÃO o fornecedor vencedor. Usada como fonte primária de descoberta.
PNCP_SEARCH_URL = "https://pncp.gov.br/api/search/"

# Consulta API oficial (Lei 14.133) — traz o detalhe completo, incluindo o
# fornecedor (niFornecedor/nomeRazaoSocialFornecedor). Usada para enriquecer
# cada contrato. Atenção: este serviço sofre indisponibilidades (HTTP 504).
PNCP_CONSULTA_URL = "https://pncp.gov.br/api/consulta"


# ---------------------------------------------------------------------------
# CNPJs dos órgãos públicos locais (placeholders — confirmar)
# ---------------------------------------------------------------------------
# CNPJ da Prefeitura de Barretos ("MUNICIPIO DE BARRETOS") — confirmado via PNCP.
CNPJ_PREFEITURA = "44780609000104"

# PLACEHOLDER — preencher com o CNPJ real da Câmara Municipal de Barretos.
CNPJ_CAMARA = "00000000000000"


# ---------------------------------------------------------------------------
# Limiares de análise (Etapa 6 — motor de bandeiras)
# ---------------------------------------------------------------------------
# Idade mínima (em meses) abaixo da qual uma empresa recém-aberta vira bandeira.
LIMIAR_EMPRESA_NOVA_MESES = 6

# Percentual de aditivo sobre o valor original que dispara bandeira (ex.: 0.25 = 25%).
LIMIAR_ADITIVO_PERCENTUAL = 0.25

# Fração do valor total concentrada em poucos fornecedores que dispara bandeira.
LIMIAR_CONCENTRACAO = 0.50
