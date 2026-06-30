"""
Motor de indicadores — bandeiras vermelhas (Etapa 6).

O coração analítico, e **tudo explicável**. Cada regra é uma **função pura**
que recebe os dados de que precisa e devolve `None` ou uma `Bandeira` com
código, descrição legível, evidência (os dados que a justificam) e peso.

Nenhuma bandeira é um veredito: é um *indício que merece apuração*, sempre
rastreável até o dado oficial. O `avaliar` agrega as regras sobre um contrato
e devolve as bandeiras + um "nível de atenção" (soma dos pesos).

As regras que dependem de dados ainda não coletados (participantes da
licitação, aditivos, preço unitário por item) já existem como funções puras
testadas — basta alimentá-las quando a Etapa 2B/itens chegar.
"""

from __future__ import annotations

import config
from src.models import Bandeira
from src.normalize.entidades import idade_empresa_meses

# Pesos por regra (quanto maior, mais grave). Concentrados aqui para ajuste fácil.
PESOS = {
    "DISPENSA_INEXIGIBILIDADE": 2,
    "EMPRESA_NOVA": 3,
    "FORNECEDOR_SANCIONADO": 5,
    "SITUACAO_CADASTRAL": 4,
    "PARTICIPANTE_UNICO": 3,
    "CONCENTRACAO": 2,
    "ADITIVO_ELEVADO": 3,
    "SOBREPRECO": 4,
    "FIM_DE_EXERCICIO": 1,
}


# ---------------------------------------------------------------------------
# Regras (uma função pura por regra)
# ---------------------------------------------------------------------------
def dispensa_inexigibilidade(modalidade: str | None) -> Bandeira | None:
    """Contratação direta (dispensa ou inexigibilidade) — menos competição."""
    if not modalidade:
        return None
    m = modalidade.lower()
    if "dispensa" in m or "inexigibilidade" in m:
        return Bandeira(
            codigo="DISPENSA_INEXIGIBILIDADE",
            descricao=f"Contratação direta por {modalidade}",
            evidencia={"modalidade": modalidade},
            peso=PESOS["DISPENSA_INEXIGIBILIDADE"],
        )
    return None


def empresa_recem_aberta(
    data_inicio_atividade: str | None,
    data_contrato: str | None,
    limiar_meses: int = config.LIMIAR_EMPRESA_NOVA_MESES,
) -> Bandeira | None:
    """Empresa aberta há menos de N meses na data do contrato."""
    idade = idade_empresa_meses(data_inicio_atividade, data_contrato)
    if idade is None or idade >= limiar_meses:
        return None
    return Bandeira(
        codigo="EMPRESA_NOVA",
        descricao=f"Empresa com {idade} meses na data do contrato (< {limiar_meses})",
        evidencia={
            "data_inicio_atividade": data_inicio_atividade,
            "data_contrato": data_contrato,
            "idade_meses": idade,
        },
        peso=PESOS["EMPRESA_NOVA"],
    )


def fornecedor_ou_socio_sancionado(sancoes_do_alvo: list[dict] | None) -> Bandeira | None:
    """Fornecedor (ou um sócio) consta em lista de sanção (CEIS/CNEP/apenados)."""
    if not sancoes_do_alvo:
        return None
    fontes = sorted({s.get("fonte") for s in sancoes_do_alvo if s.get("fonte")})
    exemplo = sancoes_do_alvo[0]
    return Bandeira(
        codigo="FORNECEDOR_SANCIONADO",
        descricao=f"Fornecedor/sócio sancionado ({', '.join(fontes)})",
        evidencia={
            "fontes": fontes,
            "qtde": len(sancoes_do_alvo),
            "exemplo": {
                "fonte": exemplo.get("fonte"),
                "categoria": exemplo.get("categoria"),
                "nome_sancionado": exemplo.get("nome_sancionado"),
                "vinculo": exemplo.get("vinculo"),
            },
        },
        peso=PESOS["FORNECEDOR_SANCIONADO"],
    )


def situacao_cadastral_irregular(
    situacao_cadastral: str | None, situacao_especial: str | None = None
) -> Bandeira | None:
    """Empresa não-ATIVA (baixada/inapta/suspensa) ou com situação especial."""
    sit = (situacao_cadastral or "").strip().upper()
    irregular = bool(sit) and sit != "ATIVA"
    especial = bool((situacao_especial or "").strip())
    if not irregular and not especial:
        return None
    motivo = sit if irregular else f"situação especial: {situacao_especial}"
    return Bandeira(
        codigo="SITUACAO_CADASTRAL",
        descricao=f"Situação cadastral irregular ({motivo})",
        evidencia={
            "situacao_cadastral": situacao_cadastral,
            "situacao_especial": situacao_especial,
        },
        peso=PESOS["SITUACAO_CADASTRAL"],
    )


def participante_unico(num_participantes: int | None) -> Bandeira | None:
    """Apenas um participante na licitação (competição inexistente)."""
    if num_participantes is None or num_participantes != 1:
        return None
    return Bandeira(
        codigo="PARTICIPANTE_UNICO",
        descricao="Licitação com participante único",
        evidencia={"num_participantes": num_participantes},
        peso=PESOS["PARTICIPANTE_UNICO"],
    )


def concentracao_fornecedor(
    valor_fornecedor: float | None,
    valor_total: float | None,
    limiar_fracao: float = config.LIMIAR_CONCENTRACAO,
) -> Bandeira | None:
    """Um fornecedor concentra fatia do gasto total acima do limiar."""
    if not valor_fornecedor or not valor_total or valor_total <= 0:
        return None
    fracao = valor_fornecedor / valor_total
    if fracao < limiar_fracao:
        return None
    return Bandeira(
        codigo="CONCENTRACAO",
        descricao=f"Fornecedor concentra {fracao:.0%} do gasto (≥ {limiar_fracao:.0%})",
        evidencia={
            "valor_fornecedor": round(valor_fornecedor, 2),
            "valor_total": round(valor_total, 2),
            "fracao": round(fracao, 4),
        },
        peso=PESOS["CONCENTRACAO"],
    )


def aditivo_eleva_valor(
    valor_original: float | None,
    valor_atual: float | None,
    limiar_pct: float = config.LIMIAR_ADITIVO_PERCENTUAL,
) -> Bandeira | None:
    """Aditivos elevam o valor do contrato acima de X% do original."""
    if not valor_original or valor_original <= 0 or valor_atual is None:
        return None
    acrescimo = (valor_atual - valor_original) / valor_original
    if acrescimo < limiar_pct:
        return None
    return Bandeira(
        codigo="ADITIVO_ELEVADO",
        descricao=f"Aditivos elevaram o valor em {acrescimo:.0%} (≥ {limiar_pct:.0%})",
        evidencia={
            "valor_original": round(valor_original, 2),
            "valor_atual": round(valor_atual, 2),
            "acrescimo": round(acrescimo, 4),
        },
        peso=PESOS["ADITIVO_ELEVADO"],
    )


def sobrepreco_item(
    preco_unitario: float | None,
    mediana_item: float | None,
    fator: float = 2.0,
) -> Bandeira | None:
    """Preço unitário muito acima da mediana do mesmo item (sobrepreço)."""
    if not preco_unitario or not mediana_item or mediana_item <= 0:
        return None
    razao = preco_unitario / mediana_item
    if razao < fator:
        return None
    return Bandeira(
        codigo="SOBREPRECO",
        descricao=f"Preço unitário {razao:.1f}x a mediana do item (≥ {fator}x)",
        evidencia={
            "preco_unitario": preco_unitario,
            "mediana_item": mediana_item,
            "razao": round(razao, 2),
        },
        peso=PESOS["SOBREPRECO"],
    )


def fim_de_exercicio(data_contrato: str | None) -> Bandeira | None:
    """Gasto concentrado em dezembro (corrida de fim de exercício)."""
    if not data_contrato or len(data_contrato) < 7:
        return None
    if data_contrato[5:7] != "12":
        return None
    return Bandeira(
        codigo="FIM_DE_EXERCICIO",
        descricao="Contrato firmado em dezembro (fim de exercício)",
        evidencia={"data_contrato": data_contrato},
        peso=PESOS["FIM_DE_EXERCICIO"],
    )


# ---------------------------------------------------------------------------
# Agregador
# ---------------------------------------------------------------------------
def avaliar(contrato: dict, contexto: dict | None = None) -> dict:
    """
    Roda todas as regras sobre um contrato + contexto e devolve:
        {"bandeiras": [Bandeira, ...], "nivel_atencao": int}

    `contrato` traz os campos do próprio contrato (modalidade, data, valor...).
    `contexto` traz o que vem de outras tabelas/cálculos (empresa, sanções,
    totais, aditivos, participantes...). Regras sem dados retornam None e são
    simplesmente ignoradas.
    """
    ctx = contexto or {}
    candidatas = [
        dispensa_inexigibilidade(contrato.get("modalidade")),
        empresa_recem_aberta(
            ctx.get("data_inicio_atividade"),
            contrato.get("data"),
            ctx.get("limiar_empresa_meses", config.LIMIAR_EMPRESA_NOVA_MESES),
        ),
        fornecedor_ou_socio_sancionado(ctx.get("sancoes")),
        situacao_cadastral_irregular(
            ctx.get("situacao_cadastral"), ctx.get("situacao_especial")
        ),
        participante_unico(ctx.get("num_participantes")),
        concentracao_fornecedor(ctx.get("valor_fornecedor"), ctx.get("valor_total")),
        aditivo_eleva_valor(ctx.get("valor_original"), contrato.get("valor")),
        sobrepreco_item(ctx.get("preco_unitario"), ctx.get("mediana_item")),
        fim_de_exercicio(contrato.get("data")),
    ]
    bandeiras = [b for b in candidatas if b is not None]
    return {
        "bandeiras": bandeiras,
        "nivel_atencao": sum(b.peso for b in bandeiras),
    }
