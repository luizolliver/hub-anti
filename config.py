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


# ---------------------------------------------------------------------------
# CNPJs dos órgãos públicos locais (placeholders — confirmar)
# ---------------------------------------------------------------------------
# PLACEHOLDER — preencher com o CNPJ real da Prefeitura de Barretos.
CNPJ_PREFEITURA = "00000000000000"

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
