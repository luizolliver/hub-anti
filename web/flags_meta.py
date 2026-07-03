"""
Metadados de apresentação das bandeiras (camada web, NÃO de dados).

Mapeia cada `codigo` de bandeira (ver `src/analysis/flags.py` → PESOS) para um
rótulo amigável, uma explicação em linguagem simples e um tom visual:

  - "red"   → sinal grave (situação cadastral, sanção, sem licitação…);
  - "amber" → sinal de contexto/atenção moderada.

O tom é só cor no chip — NÃO altera peso nem o nível (isso vive na camada de
dados, já testada). Todos os códigos de PESOS estão cobertos aqui para que a UI
nunca receba um chip sem legenda.
"""

FLAGS_META: dict[str, dict[str, str]] = {
    # ---- graves (vermelho) ----
    "SITUACAO_CADASTRAL": {
        "label": "Cadastro irregular",
        "desc": "Situação da empresa na Receita Federal não está ativa (ex.: INAPTA, SUSPENSA, BAIXADA).",
        "tone": "red",
    },
    "FORNECEDOR_SANCIONADO": {
        "label": "Sanção ativa",
        "desc": "Empresa ou sócio consta em cadastro de sanções (CEIS/CNEP).",
        "tone": "red",
    },
    "SOBREPRECO": {
        "label": "Indício de sobrepreço",
        "desc": "Valor contratado acima da referência esperada para o objeto.",
        "tone": "red",
    },
    "DISPENSA_ACIMA_LIMITE": {
        "label": "Dispensa acima do limite",
        "desc": "Dispensa em razão do valor acima do teto legal vigente no ano do contrato "
                "(não inclui inexigibilidade nem dispensa emergencial).",
        "tone": "red",
    },
    "ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO": {
        "label": "Repasse sem licitação",
        "desc": "Entidade sem fins lucrativos recebendo recursos sem processo licitatório.",
        "tone": "red",
    },
    "MULTIPLOS_CONTRATOS_OBJETO_SIMILAR": {
        "label": "Contratos de objeto similar",
        "desc": "Vários contratos de objeto parecido — possível fracionamento para evitar licitação.",
        "tone": "red",
    },
    # ---- atenção moderada (âmbar) ----
    "EMPRESA_NOVA": {
        "label": "Empresa recém-aberta",
        "desc": "Empresa criada pouco antes de contratar com o poder público.",
        "tone": "amber",
    },
    "EMPRESA_NOVA_NO_CONTRATO": {
        "label": "Empresa nova no contrato",
        "desc": "Empresa aberta há pouco tempo na data do contrato específico.",
        "tone": "amber",
    },
    "DISPENSA_INEXIGIBILIDADE": {
        "label": "Dispensa / inexigibilidade",
        "desc": "Contratação direta, sem disputa aberta entre fornecedores.",
        "tone": "amber",
    },
    "PARTICIPANTE_UNICO": {
        "label": "Participante único",
        "desc": "Certame com um único participante — concorrência limitada.",
        "tone": "amber",
    },
    "CONCENTRACAO": {
        "label": "Concentração de contratos",
        "desc": "Parcela relevante das contratações do período concentrada neste fornecedor.",
        "tone": "amber",
    },
    "CONCENTRACAO_POR_SECRETARIA": {
        "label": "Concentração por secretaria",
        "desc": "Fornecedor concentra contratos dentro de uma mesma secretaria/órgão.",
        "tone": "amber",
    },
    "ADITIVO_ELEVADO": {
        "label": "Aditivo elevado",
        "desc": "Aditivos que elevam bastante o valor original do contrato.",
        "tone": "amber",
    },
    "FIM_DE_EXERCICIO": {
        "label": "Gasto em fim de exercício",
        "desc": "Contratação concentrada no fim do exercício financeiro.",
        "tone": "amber",
    },
    "SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS": {
        "label": "Sócio em várias fornecedoras",
        "desc": "Um mesmo sócio aparece em várias empresas que fornecem ao município.",
        "tone": "amber",
    },
}
