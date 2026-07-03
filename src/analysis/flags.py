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

import datetime

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
    # Bandeiras adicionais (Parte 2), de nível de fornecedor.
    "EMPRESA_NOVA_NO_CONTRATO": 3,
    "DISPENSA_ACIMA_LIMITE": 3,
    "ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO": 4,
    "CONCENTRACAO_POR_SECRETARIA": 2,
    "MULTIPLOS_CONTRATOS_OBJETO_SIMILAR": 4,
    "SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS": 3,
}


def _data(iso: str | None) -> datetime.date | None:
    """Converte 'AAAA-MM-DD' em date, tolerante. None se vazio/inválido."""
    if not iso or len(iso) < 10:
        return None
    try:
        return datetime.date.fromisoformat(iso[:10])
    except ValueError:
        return None


def _eh_contratacao_direta(modalidade: str | None) -> bool:
    """True se a modalidade é dispensa/inexigibilidade/contratação direta."""
    m = (modalidade or "").lower()
    return "dispensa" in m or "inexigib" in m or "direta" in m


def _eh_obra(objeto: str | None) -> bool:
    """Heurística simples: o objeto parece obra/serviço de engenharia?"""
    o = (objeto or "").lower()
    termos = ("obra", "pavimenta", "construç", "construc", "reforma", "engenharia",
              "recapeament", "drenagem", "edificaç", "edificac", "terraplan")
    return any(t in o for t in termos)


def _eh_dispensa_por_valor(modalidade: str | None, objeto: str | None) -> bool:
    """
    True apenas para DISPENSA "em razão do valor" — a única hipótese de
    contratação direta com teto de valor.

    Fica de fora (não têm teto de valor, logo não são "acima do limite"):
      - inexigibilidade (art. 74 — inviabilidade de competição, qualquer valor);
      - dispensa emergencial/calamidade (art. 75 VIII / 8.666 art. 24 IV).
    """
    m = (modalidade or "").lower()
    o = (objeto or "").lower()
    if "inexig" in m:
        return False
    if "dispensa" not in m and "direta" not in m:
        return False
    if any(t in o for t in ("emergenc", "emergênc", "calamid")):
        return False
    return True


def _brl(v: float) -> str:
    """Formata em Real no padrão pt-BR (R$ 1.234,56)."""
    return f"R$ {v:,.2f}".replace(",", "§").replace(".", ",").replace("§", ".")


def _limite_dispensa(data: str | None, eh_obra: bool) -> tuple[float, str]:
    """
    Teto da dispensa por valor VIGENTE na data do contrato (ver
    `config.LIMITES_DISPENSA`). Sem data, usa o teto mais recente (conservador:
    evita falso positivo). Retorna (limite, vigencia_inicio).
    """
    d = _data(data)
    ref = d.isoformat() if d else "9999-12-31"
    escolhido = config.LIMITES_DISPENSA[0]
    for faixa in config.LIMITES_DISPENSA:
        if ref >= faixa[0]:
            escolhido = faixa
        else:
            break
    inicio, teto_obra, teto_bs = escolhido
    return (teto_obra if eh_obra else teto_bs), inicio


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
# Bandeiras de nível de fornecedor (Parte 2) — operam sobre o conjunto de
# contratos do fornecedor e seu cadastro, não sobre um contrato isolado.
# ---------------------------------------------------------------------------
def empresa_nova_no_contrato(
    data_abertura: str | None,
    contratos: list[dict] | None,
    limiar_dias: int = config.LIMIAR_EMPRESA_NOVA_CONTRATO_DIAS,
) -> Bandeira | None:
    """Empresa constituída há menos de `limiar_dias` na data do 1º contrato."""
    abertura = _data(data_abertura)
    datas = sorted(d for d in (_data(c.get("data")) for c in (contratos or [])) if d)
    if not abertura or not datas:
        return None
    primeiro = datas[0]
    dias = (primeiro - abertura).days
    if dias < 0 or dias >= limiar_dias:
        return None
    return Bandeira(
        codigo="EMPRESA_NOVA_NO_CONTRATO",
        descricao="Empresa constituída há menos de 1 ano na data do primeiro contrato com o município",
        evidencia={
            "data_abertura": data_abertura,
            "data_primeiro_contrato": primeiro.isoformat(),
            "dias": dias,
        },
        peso=PESOS["EMPRESA_NOVA_NO_CONTRATO"],
    )


def dispensa_acima_limite(contratos: list[dict] | None) -> Bandeira | None:
    """
    Dispensa "em razão do valor" acima do teto legal VIGENTE na data do contrato.

    Compara cada contrato ao teto do seu ano (`config.LIMITES_DISPENSA`), porque
    os contratos cruzam a Lei 8.666 e a Lei 14.133 — um teto fixo geraria falso
    positivo em contrato recente e falso negativo em contrato antigo. Considera
    apenas dispensa por valor: inexigibilidade e dispensa emergencial não têm
    teto de valor e ficam de fora (ver `_eh_dispensa_por_valor`).
    """
    pior = None  # (excedente, valor, limite, vigencia, contrato)
    for c in contratos or []:
        if not _eh_dispensa_por_valor(c.get("modalidade"), c.get("objeto")):
            continue
        valor = c.get("valor") or 0
        limite, vigencia = _limite_dispensa(c.get("data"), _eh_obra(c.get("objeto")))
        if valor > limite:
            excedente = valor - limite
            if pior is None or excedente > pior[0]:
                pior = (excedente, valor, limite, vigencia, c)
    if not pior:
        return None
    _, valor, limite, vigencia, c = pior
    return Bandeira(
        codigo="DISPENSA_ACIMA_LIMITE",
        descricao=(
            f"Dispensa de {_brl(valor)} acima do teto legal de {_brl(limite)} "
            f"(vigente desde {vigencia}) — exige justificativa formal"
        ),
        evidencia={
            "modalidade": c.get("modalidade"),
            "valor": round(valor, 2),
            "limite_vigente": limite,
            "vigencia_desde": vigencia,
            "objeto": (c.get("objeto") or "")[:80],
            "data": c.get("data"),
        },
        peso=PESOS["DISPENSA_ACIMA_LIMITE"],
    )


def entidade_sem_fins_sem_licitacao(
    natureza_juridica: str | None, contratos: list[dict] | None
) -> Bandeira | None:
    """Entidade sem fins lucrativos (associação/fundação/OSCIP) contratada sem licitação."""
    nat = (natureza_juridica or "").lower()
    sem_fins = any(t in nat for t in ("associa", "fundaç", "fundac", "oscip", "sem fins", "organização social", "organizacao social"))
    if not sem_fins:
        return None
    direto = next((c for c in (contratos or []) if _eh_contratacao_direta(c.get("modalidade"))), None)
    if not direto:
        return None
    return Bandeira(
        codigo="ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO",
        descricao=(
            "Entidade sem fins lucrativos contratada sem processo licitatório — "
            "comum em repasses irregulares via convênio"
        ),
        evidencia={
            "natureza_juridica": natureza_juridica,
            "modalidade": direto.get("modalidade"),
            "objeto": (direto.get("objeto") or "")[:80],
            "valor": direto.get("valor"),
        },
        peso=PESOS["ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO"],
    )


def concentracao_por_secretaria(
    contratos: list[dict] | None,
    totais_orgao_ano: dict | None,
    limiar_fracao: float = config.LIMIAR_CONCENTRACAO_SECRETARIA,
) -> Bandeira | None:
    """
    Fornecedor concentra > limiar do valor contratado por um único órgão num ano.

    `totais_orgao_ano` mapeia (orgao, ano) -> {'total': float, 'n': int} sobre
    TODOS os fornecedores. Para evitar ruído (órgão-ano com 1 só contrato),
    exige pelo menos 3 contratos no grupo.
    """
    if not contratos or not totais_orgao_ano:
        return None
    por_grupo: dict[tuple, float] = {}
    for c in contratos:
        chave = (c.get("orgao"), c.get("ano"))
        por_grupo[chave] = por_grupo.get(chave, 0.0) + (c.get("valor") or 0)
    pior = None
    for chave, valor_forn in por_grupo.items():
        info = totais_orgao_ano.get(chave)
        if not info or info["total"] <= 0 or info["n"] < 3:
            continue
        fracao = valor_forn / info["total"]
        if fracao >= limiar_fracao and (pior is None or fracao > pior[0]):
            pior = (fracao, chave, valor_forn, info)
    if not pior:
        return None
    fracao, (orgao, ano), valor_forn, info = pior
    return Bandeira(
        codigo="CONCENTRACAO_POR_SECRETARIA",
        descricao=(
            f"Fornecedor concentra {fracao:.0%} dos contratos de {orgao} no ano "
            f"{ano} — possível direcionamento ou dependência"
        ),
        evidencia={
            "orgao": orgao, "ano": ano, "fracao": round(fracao, 4),
            "valor_fornecedor": round(valor_forn, 2),
            "valor_orgao_ano": round(info["total"], 2),
            "contratos_no_orgao_ano": info["n"],
        },
        peso=PESOS["CONCENTRACAO_POR_SECRETARIA"],
    )


def multiplos_contratos_objeto_similar(
    contratos: list[dict] | None,
    min_contratos: int = config.FRACIONAMENTO_MIN_CONTRATOS,
    janela_dias: int = config.FRACIONAMENTO_JANELA_DIAS,
    prefixo: int = config.FRACIONAMENTO_PREFIXO_OBJETO,
) -> Bandeira | None:
    """
    3+ contratos com o mesmo órgão e objeto similar (mesmo prefixo) numa janela
    de `janela_dias` — indício clássico de fracionamento de despesa.
    """
    grupos: dict[tuple, list] = {}
    for c in contratos or []:
        d = _data(c.get("data"))
        obj = (c.get("objeto") or "").strip().lower()[:prefixo]
        if not d or not obj:
            continue
        grupos.setdefault((c.get("orgao"), obj), []).append((d, c))
    for (orgao, obj), itens in grupos.items():
        if len(itens) < min_contratos:
            continue
        datas = sorted(d for d, _ in itens)
        # janela deslizante: existe alguma janela com min_contratos datas?
        for i in range(len(datas) - min_contratos + 1):
            if (datas[i + min_contratos - 1] - datas[i]).days <= janela_dias:
                return Bandeira(
                    codigo="MULTIPLOS_CONTRATOS_OBJETO_SIMILAR",
                    descricao=(
                        "Múltiplos contratos com objeto similar em curto período — "
                        "possível fracionamento para evitar licitação"
                    ),
                    evidencia={
                        "orgao": orgao,
                        "objeto_prefixo": obj,
                        "qtde": len(itens),
                        "janela_dias": (datas[i + min_contratos - 1] - datas[i]).days,
                        "primeira_data": datas[i].isoformat(),
                    },
                    peso=PESOS["MULTIPLOS_CONTRATOS_OBJETO_SIMILAR"],
                )
    return None


def socio_multiplas_empresas_fornecedoras(
    n_empresas_fornecedoras: int | None,
    minimo: int = config.SOCIO_MIN_EMPRESAS_FORNECEDORAS,
) -> Bandeira | None:
    """Um sócio aparece em `minimo`+ empresas que contratam com a prefeitura."""
    n = n_empresas_fornecedoras or 0
    if n < minimo:
        return None
    return Bandeira(
        codigo="SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS",
        descricao=(
            f"Sócio em comum a {n} empresas fornecedoras do município — "
            "possível grupo econômico atuando como concorrentes"
        ),
        evidencia={"empresas_fornecedoras": n},
        peso=PESOS["SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS"],
    )


def avaliar_fornecedor(ctx: dict) -> dict:
    """
    Agrega TODAS as bandeiras de nível de fornecedor a partir de um contexto já
    montado (fonte única de verdade, usada pelo ranking e pelo dossiê).

    `ctx` esperado:
        situacao_cadastral, situacao_especial, natureza_juridica,
        data_inicio_atividade, sancoes (list), valor_pago, total_pago,
        contratos (list de {data, modalidade, valor, objeto, orgao, ano}),
        totais_orgao_ano (dict), n_empresas_irmas_fornecedoras (int)
    """
    contratos = ctx.get("contratos") or []
    candidatas = [
        situacao_cadastral_irregular(ctx.get("situacao_cadastral"), ctx.get("situacao_especial")),
        fornecedor_ou_socio_sancionado(ctx.get("sancoes")),
        concentracao_fornecedor(ctx.get("valor_pago"), ctx.get("total_pago")),
        empresa_nova_no_contrato(ctx.get("data_inicio_atividade"), contratos),
        dispensa_acima_limite(contratos),
        entidade_sem_fins_sem_licitacao(ctx.get("natureza_juridica"), contratos),
        concentracao_por_secretaria(contratos, ctx.get("totais_orgao_ano")),
        multiplos_contratos_objeto_similar(contratos),
        socio_multiplas_empresas_fornecedoras(ctx.get("n_empresas_irmas_fornecedoras")),
    ]
    bandeiras = [b for b in candidatas if b is not None]
    return {"bandeiras": bandeiras, "nivel_atencao": sum(b.peso for b in bandeiras)}


# ---------------------------------------------------------------------------
# Agregador (nível de contrato)
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
