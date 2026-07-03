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

# Como Barretos aparece DENTRO dos CSVs em massa do TCE-SP (a confirmar na 2B).
# Provavelmente o nome "BARRETOS"; pode também ser um código de município do TCE.
# PLACEHOLDER — confirmar ao inspecionar os arquivos CSV reais do TCE-SP.
CODIGO_TCE_MUNICIPIO = "BARRETOS"

# Slug do município na API REST do TCE-SP (confirmado em /api/json/municipios).
TCE_MUNICIPIO_SLUG = "barretos"

# Base da API REST do TCE-SP (Despesas 2014–2019; protótipo da Etapa 2A).
TCE_REST_URL = "https://transparencia.tce.sp.gov.br/api/json"

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

# Consulta API oficial (Lei 14.133) — filtros por data/órgão. Atenção: sofre
# indisponibilidades (HTTP 504). Mantida para consultas agregadas.
PNCP_CONSULTA_URL = "https://pncp.gov.br/api/consulta"

# API de detalhe do PNCP — traz o contrato completo, incluindo o fornecedor
# (niFornecedor/nomeRazaoSocialFornecedor) em
# /v1/orgaos/{cnpj}/contratos/{ano}/{seq}. É a base correta do enriquecimento
# (a /api/consulta retorna 404 para esse caminho de detalhe).
PNCP_DETALHE_URL = "https://pncp.gov.br/api/pncp"


# ---------------------------------------------------------------------------
# CNPJs dos órgãos públicos locais (placeholders — confirmar)
# ---------------------------------------------------------------------------
# CNPJ da Prefeitura de Barretos ("MUNICIPIO DE BARRETOS") — confirmado via PNCP.
CNPJ_PREFEITURA = "44780609000104"

# PLACEHOLDER — preencher com o CNPJ real da Câmara Municipal de Barretos.
CNPJ_CAMARA = "64925829000188"


# ---------------------------------------------------------------------------
# Limiares de análise (Etapa 6 — motor de bandeiras)
# ---------------------------------------------------------------------------
# Idade mínima (em meses) abaixo da qual uma empresa recém-aberta vira bandeira.
LIMIAR_EMPRESA_NOVA_MESES = 6

# Percentual de aditivo sobre o valor original que dispara bandeira (ex.: 0.25 = 25%).
LIMIAR_ADITIVO_PERCENTUAL = 0.25

# Fração do valor total concentrada em poucos fornecedores que dispara bandeira.
LIMIAR_CONCENTRACAO = 0.50

# --- Limiares das bandeiras adicionais (Parte 2) ----------------------------
# Empresa "nova" no 1º contrato: idade (abertura → 1º contrato) abaixo disto.
LIMIAR_EMPRESA_NOVA_CONTRATO_DIAS = 365

# Limites legais da dispensa "em razão do valor", POR VIGÊNCIA. Cada contrato é
# comparado ao teto vigente na sua data (os contratos vão de 2014 a 2026,
# cruzando a Lei 8.666 e a Lei 14.133). Acima do teto, a dispensa exige
# justificativa formal — vira indício.
#
# (data_inicio_vigencia, teto_obras_engenharia, teto_bens_e_servicos)
# Fontes:
#   Lei 8.666/93 art. 24 I/II (red. Lei 9.648/98): R$ 15.000 / R$ 8.000
#   Decreto 9.412/2018 (vig. 19/07/2018):          R$ 33.000 / R$ 17.600
#   Lei 14.133/2021 art. 75 I/II (original):       R$ 100.000 / R$ 50.000
#   Decreto 11.317/2022 (vig. 01/01/2023):         R$ 114.416,66 / R$ 57.208,33
#   Decreto 11.871/2023 (vig. 01/01/2024):         R$ 119.812,02 / R$ 59.906,02
#   Decreto 12.343/2024 (vig. 01/01/2025):         R$ 125.451,15 / R$ 62.725,59
#   Decreto 12.807/2025 (vig. 01/01/2026):         R$ 130.984,20 / R$ 65.492,11
# Na transição 2021–2023 (coexistência 8.666/14.133), usamos o teto MAIOR
# (14.133) para não gerar falso positivo.
LIMITES_DISPENSA = [
    ("0001-01-01", 15000.00, 8000.00),
    ("2018-07-19", 33000.00, 17600.00),
    ("2021-04-01", 100000.00, 50000.00),
    ("2023-01-01", 114416.66, 57208.33),
    ("2024-01-01", 119812.02, 59906.02),
    ("2025-01-01", 125451.15, 62725.59),
    ("2026-01-01", 130984.20, 65492.11),
]

# Concentração por órgão/secretaria: fração dos contratos de um órgão, num ano,
# concentrada num único fornecedor que dispara a bandeira.
LIMIAR_CONCENTRACAO_SECRETARIA = 0.40

# Fracionamento: nº mínimo de contratos com objeto similar (mesmo prefixo) no
# mesmo órgão dentro da janela, e o tamanho da janela e do prefixo do objeto.
FRACIONAMENTO_MIN_CONTRATOS = 3
FRACIONAMENTO_JANELA_DIAS = 90
FRACIONAMENTO_PREFIXO_OBJETO = 40

# Sócio em múltiplas fornecedoras: nº mínimo de empresas fornecedoras (incluindo
# a própria) que compartilham um mesmo sócio para disparar a bandeira.
SOCIO_MIN_EMPRESAS_FORNECEDORAS = 3
