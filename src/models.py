"""
Modelos de dados (pydantic) do Observatório.

Por enquanto há apenas o `Contrato`, o registro canônico unificado que
recebe dados tanto do PNCP (Etapa 1) quanto do TCE-SP (Etapa 2). Manter o
modelo único desde já evita retrabalho na reconciliação (Etapa 3).
"""

from __future__ import annotations

import hashlib
import json
import re

from pydantic import BaseModel, Field

from src.normalize.entidades import digitos_visiveis, normalizar_cnpj, normalizar_nome


def _so_digitos(valor: str | None) -> str | None:
    """Mantém apenas os dígitos de um documento (CNPJ/CPF). None se vazio."""
    if not valor:
        return None
    digitos = re.sub(r"\D", "", valor)
    return digitos or None


def parse_id_fornecedor(id_fornecedor: str | None) -> tuple[str, str | None]:
    """
    Interpreta o campo `id_fornecedor` do TCE-SP.

    Formatos observados:
      - 'CNPJ - PESSOA JURÍDICA - 02558157000162'   -> ('CNPJ', '02558157000162')
      - 'PESSOA FÍSICA - 114968'                     -> ('CPF', None)  # CPF mascarado pelo TCE
      - 'IDENTIFICAÇÃO ESPECIAL - SEM CPF/CNPJ - ...'-> ('OUTRO', None)
      - 'INSCRIÇÃO GENÉRICA-OUTROS - ...'            -> ('OUTRO', None)

    Só devolvemos o documento quando é um CNPJ válido em comprimento (14 díg.),
    pois é a única chave confiável para cruzar fornecedores. CPFs vêm mascarados
    (LGPD) e não são reconstruíveis.
    """
    if not id_fornecedor:
        return ("OUTRO", None)
    partes = [p.strip() for p in id_fornecedor.split(" - ")]
    tipo = partes[0].upper()
    if tipo == "CNPJ":
        doc = _so_digitos(partes[-1])
        return ("CNPJ", doc if doc and len(doc) == 14 else None)
    if tipo.startswith("PESSOA F"):  # PESSOA FÍSICA
        return ("CPF", None)
    return ("OUTRO", None)


def parse_valor_br(valor: str | None) -> float | None:
    """Converte valor monetário brasileiro ('1.582,98' / '289,61') em float."""
    if valor is None or str(valor).strip() == "":
        return None
    txt = str(valor).strip().replace(".", "").replace(",", ".")
    try:
        return float(txt)
    except ValueError:
        return None


def parse_data_br(data: str | None) -> str | None:
    """Converte 'DD/MM/AAAA' em ISO 'AAAA-MM-DD'. None se vazio/inválido."""
    if not data:
        return None
    m = re.match(r"^\s*(\d{2})/(\d{2})/(\d{4})\s*$", data)
    if not m:
        return None
    dia, mes, ano = m.groups()
    return f"{ano}-{mes}-{dia}"


class Contrato(BaseModel):
    """
    Um contrato/ajuste público, normalizado.

    O campo `id` é o identificador canônico usado para deduplicação. No PNCP
    é o `numero_controle_pncp` (ex.: '44780609000104-2-000069/2026').
    """

    id: str
    fonte: str  # 'PNCP' ou 'TCE-SP'
    id_origem: str | None = None  # identificador/url original na fonte

    orgao: str | None = None  # nome do órgão contratante
    orgao_cnpj: str | None = None

    objeto: str | None = None
    modalidade: str | None = None

    # Fornecedor vencedor. No PNCP só é conhecido após enriquecer pelo detalhe
    # da API de consulta; por isso é opcional.
    fornecedor_cnpj: str | None = None
    fornecedor_nome: str | None = None

    valor: float | None = None
    data: str | None = None  # data de assinatura, ISO (AAAA-MM-DD)
    ano: str | None = None

    municipio_ibge: str | None = None
    municipio_nome: str | None = None
    uf: str | None = None

    # JSON bruto da fonte, para auditoria/reprocessamento.
    raw: dict = Field(default_factory=dict)

    def para_linha_db(self) -> dict:
        """Converte para um dict pronto para inserir na tabela `contratos`."""
        d = self.model_dump(exclude={"raw"})
        d["raw"] = json.dumps(self.raw, ensure_ascii=False)
        return d

    @classmethod
    def from_pncp_search(cls, item: dict, municipio_ibge: str | None = None) -> "Contrato":
        """
        Constrói um Contrato a partir de um item da search API do PNCP.

        O fornecedor não vem nessa fonte (fica None até o enriquecimento via
        API de consulta).
        """
        return cls(
            id=item["numero_controle_pncp"],
            fonte="PNCP",
            id_origem=item.get("item_url"),
            orgao=item.get("orgao_nome"),
            orgao_cnpj=_so_digitos(item.get("orgao_cnpj")),
            objeto=item.get("description") or item.get("title"),
            modalidade=item.get("modalidade_licitacao_nome"),
            valor=item.get("valor_global"),
            data=item.get("data_assinatura"),
            ano=str(item["ano"]) if item.get("ano") is not None else None,
            municipio_ibge=municipio_ibge,
            municipio_nome=item.get("municipio_nome"),
            uf=item.get("uf"),
            raw=item,
        )

    @classmethod
    def from_tce_ajuste(cls, row: dict, municipio_ibge: str | None = None) -> "Contrato":
        """
        Constrói um Contrato a partir de uma linha do arquivo de **Ajustes** do
        Cubo Audesp Fase IV do TCE-SP (Etapa 2B). É o lado-contrato do TCE, que
        — ao contrário das despesas — traz o fornecedor contratado (CNPJ + nome).

        Chave canônica: o **Código do Ajuste** (identificador único do contrato
        no TCE). Os arquivos vêm em nível de item; a deduplicação por esse código
        é responsabilidade do coletor (`parsear_ajustes`).

        Particularidades do arquivo (dados reais, irregulares):
          - O CNPJ vem formatado ('05.808.979/0001-42') -> só dígitos.
          - Em ajustes cujo instrumento é "Nota de Empenho", as colunas de
            contrato (nº/valor/assinatura) vêm vazias; nesses casos caímos para
            o valor/data da própria nota de empenho, que é o instrumento do
            ajuste. Honesto: o valor sai do que de fato vincula aquele ajuste.
        """
        codigo = (_coluna(row, "Código do Ajuste") or "").strip()
        valor = parse_valor_br(_coluna(row, "Valor total do contrato")) or parse_valor_br(
            _coluna(row, "Valor da Nota de Empenho")
        )
        data = parse_data_br(_coluna(row, "Vigência do contrato - Data Assinatura")) or parse_data_br(
            _coluna(row, "Data da Nota de Empenho")
        )
        ano = _coluna(row, "Ano do contrato") or _coluna(row, "Ano do processo licitatório")
        objeto = (
            _coluna(row, "Descrição do objeto contratado")
            or _coluna(row, "Descrição do objeto da licitação")
            or _coluna(row, "Objeto da licitação")
        )
        return cls(
            id=f"TCE-{codigo}",
            fonte="TCE-SP",
            id_origem=codigo or None,
            orgao=_coluna(row, "Entidade"),
            orgao_cnpj=None,  # o arquivo de ajustes não traz o CNPJ do órgão
            objeto=objeto,
            modalidade=_coluna(row, "Modalidade de licitação"),
            fornecedor_cnpj=_so_digitos(_coluna(row, "CNPJ da empresa contratada")),
            fornecedor_nome=_coluna(row, "Nome da empresa contratada"),
            valor=valor,
            data=data,
            ano=str(ano) if ano else None,
            municipio_ibge=municipio_ibge,
            municipio_nome=_coluna(row, "Município"),
            uf="SP",  # todo o Cubo Audesp é do estado de São Paulo
            raw=row,
        )


class Despesa(BaseModel):
    """
    Uma linha de despesa do TCE-SP (empenho/liquidação/pagamento por fornecedor).

    É a fonte **primária** do fornecedor no projeto: o campo `id_fornecedor` do
    TCE traz o CNPJ, ao contrário da search API do PNCP. Cada registro é um
    estágio (`evento`) de um empenho para um fornecedor.
    """

    id: str  # hash sintético do conteúdo (deduplicação)
    fonte: str = "TCE-SP"
    municipio: str | None = None  # slug, ex.: 'barretos'
    orgao: str | None = None
    ano: str | None = None
    mes: str | None = None
    evento: str | None = None  # Empenhado / Valor Liquidado / Valor Pago / Anulação / Reforço
    nr_empenho: str | None = None

    fornecedor_documento: str | None = None  # CNPJ (dígitos) ou None
    fornecedor_tipo: str | None = None  # CNPJ / CPF / OUTRO
    fornecedor_nome: str | None = None

    data: str | None = None  # ISO AAAA-MM-DD
    valor: float | None = None

    raw: dict = Field(default_factory=dict)

    def para_linha_db(self) -> dict:
        d = self.model_dump(exclude={"raw"})
        d["raw"] = json.dumps(self.raw, ensure_ascii=False)
        return d

    @classmethod
    def from_tce(cls, row: dict, municipio: str | None = None) -> "Despesa":
        """Constrói uma Despesa a partir de uma linha da API REST do TCE-SP."""
        tipo, doc = parse_id_fornecedor(row.get("id_fornecedor"))
        data_iso = parse_data_br(row.get("dt_emissao_despesa"))
        valor = parse_valor_br(row.get("vl_despesa"))

        # Chave de deduplicação: hash dos campos que identificam a linha.
        chave = "|".join(
            str(x)
            for x in (
                municipio,
                row.get("orgao"),
                row.get("mes"),
                row.get("evento"),
                row.get("nr_empenho"),
                row.get("id_fornecedor"),
                row.get("dt_emissao_despesa"),
                row.get("vl_despesa"),
            )
        )
        rid = hashlib.sha1(chave.encode("utf-8")).hexdigest()

        return cls(
            id=rid,
            fonte="TCE-SP",
            municipio=municipio,
            orgao=row.get("orgao"),
            mes=row.get("mes"),
            evento=row.get("evento"),
            nr_empenho=row.get("nr_empenho"),
            fornecedor_documento=doc,
            fornecedor_tipo=tipo,
            fornecedor_nome=row.get("nm_fornecedor"),
            data=data_iso,
            ano=(data_iso[:4] if data_iso else None),
            valor=valor,
            raw=row,
        )


class Empresa(BaseModel):
    """Cadastro de uma empresa (Receita Federal via BrasilAPI) — Etapa 4."""

    cnpj: str
    cnpj_raiz: str | None = None
    razao_social: str | None = None
    nome_fantasia: str | None = None
    situacao_cadastral: str | None = None  # descrição: ATIVA / BAIXADA / ...
    data_situacao_cadastral: str | None = None
    situacao_especial: str | None = None  # ex.: INTERVENCAO
    data_inicio_atividade: str | None = None  # KEY: idade da empresa (Etapa 5/6)
    natureza_juridica: str | None = None
    porte: str | None = None
    capital_social: float | None = None
    cnae: str | None = None
    cnae_descricao: str | None = None
    municipio: str | None = None
    uf: str | None = None
    matriz_filial: str | None = None  # MATRIZ / FILIAL
    raw: dict = Field(default_factory=dict)

    def para_linha_db(self) -> dict:
        d = self.model_dump(exclude={"raw"})
        d["raw"] = json.dumps(self.raw, ensure_ascii=False)
        return d

    @classmethod
    def from_brasilapi(cls, p: dict) -> "Empresa":
        cnpj = _so_digitos(p.get("cnpj")) or ""
        return cls(
            cnpj=cnpj,
            cnpj_raiz=(cnpj[:8] if len(cnpj) == 14 else None),
            razao_social=p.get("razao_social"),
            nome_fantasia=p.get("nome_fantasia"),
            situacao_cadastral=p.get("descricao_situacao_cadastral"),
            data_situacao_cadastral=p.get("data_situacao_cadastral"),
            situacao_especial=p.get("situacao_especial") or None,
            data_inicio_atividade=p.get("data_inicio_atividade"),
            natureza_juridica=p.get("natureza_juridica"),
            porte=p.get("porte"),
            capital_social=p.get("capital_social"),
            cnae=str(p["cnae_fiscal"]) if p.get("cnae_fiscal") is not None else None,
            cnae_descricao=p.get("cnae_fiscal_descricao"),
            municipio=p.get("municipio"),
            uf=p.get("uf"),
            matriz_filial=p.get("descricao_identificador_matriz_filial"),
            raw=p,
        )


class Socio(BaseModel):
    """Um sócio do quadro societário (QSA) de uma empresa — Etapa 4."""

    id: str  # hash sintético (deduplicação)
    cnpj_empresa: str
    nome_socio: str | None = None
    nome_socio_chave: str | None = None  # normalizar_nome — casamento por nome
    documento_socio: str | None = None  # como veio (CPF vem MASCARADO pela RFB)
    # Dígitos visíveis do CPF mascarado (6 do meio) — chave parcial estável que,
    # com o nome, casa a mesma pessoa entre empresas (ver nivel_vinculo_socio).
    documento_visivel: str | None = None
    cnpj_socio: str | None = None  # quando o sócio é PJ e o CNPJ é válido
    tipo_socio: str | None = None  # PF / PJ / OUTRO
    qualificacao: str | None = None
    data_entrada: str | None = None
    faixa_etaria: str | None = None
    raw: dict = Field(default_factory=dict)

    def para_linha_db(self) -> dict:
        d = self.model_dump(exclude={"raw"})
        d["raw"] = json.dumps(self.raw, ensure_ascii=False)
        return d

    @classmethod
    def from_qsa(cls, s: dict, cnpj_empresa: str) -> "Socio":
        # identificador_de_socio: 1=Pessoa Jurídica, 2=Pessoa Física, 3=Estrangeiro.
        ident = s.get("identificador_de_socio")
        tipo = {1: "PJ", 2: "PF", 3: "OUTRO"}.get(ident, "OUTRO")
        doc = s.get("cnpj_cpf_do_socio")
        cnpj_socio = normalizar_cnpj(doc) if tipo == "PJ" else None
        # Dígitos visíveis só fazem sentido para PF (CPF mascarado); para PJ a
        # chave é o cnpj_socio inteiro.
        visivel = digitos_visiveis(doc) if tipo == "PF" else None
        nome = s.get("nome_socio")
        chave = "|".join(
            str(x) for x in (cnpj_empresa, nome, doc, s.get("qualificacao_socio"),
                             s.get("data_entrada_sociedade"))
        )
        return cls(
            id=hashlib.sha1(chave.encode("utf-8")).hexdigest(),
            cnpj_empresa=cnpj_empresa,
            nome_socio=nome,
            nome_socio_chave=normalizar_nome(nome),
            documento_socio=doc,
            documento_visivel=visivel,
            cnpj_socio=cnpj_socio,
            tipo_socio=tipo,
            qualificacao=s.get("qualificacao_socio"),
            data_entrada=s.get("data_entrada_sociedade"),
            faixa_etaria=s.get("faixa_etaria"),
            raw=s,
        )


class Bandeira(BaseModel):
    """
    Uma bandeira vermelha (indício) levantada por uma regra de `analysis/flags`.

    Sempre explicável: além do código e da descrição legível, carrega a
    `evidencia` (os dados que a justificam) e um `peso` que entra no
    "nível de atenção" do contrato/fornecedor.
    """

    codigo: str
    descricao: str
    evidencia: dict = Field(default_factory=dict)
    peso: int = 1


def _coluna(row: dict, *needles: str) -> str | None:
    """
    Lê um valor de `row` por busca aproximada do nome da coluna (sem acento,
    maiúsculas). Robusto a variações de cabeçalho do CEIS/CNEP (que têm acentos
    e até erros, como 'ABRAGÊNCIA').

    Prioriza o match **exato** do nome normalizado; só então cai para a coluna
    mais curta que *contém* o needle. Isso evita capturar 'NOME INFORMADO PELO
    ÓRGÃO SANCIONADOR' quando se pede 'ÓRGÃO SANCIONADOR'.
    """
    alvo = normalizar_nome(needles[0])
    candidatos: list[tuple[int, object]] = []
    for chave, valor in row.items():
        nk = normalizar_nome(chave)
        if nk == alvo:  # match exato vence
            return (valor or None) if isinstance(valor, str) else valor
        if alvo in nk:
            candidatos.append((len(nk), valor))
    if not candidatos:
        return None
    valor = min(candidatos, key=lambda c: c[0])[1]  # a coluna mais curta que contém
    return (valor or None) if isinstance(valor, str) else valor


class Sancao(BaseModel):
    """
    Uma sanção do CEIS (inidôneas/suspensas) ou CNEP (Lei Anticorrupção),
    do Portal da Transparência federal — Etapa 5.
    """

    fonte: str  # CEIS / CNEP
    tipo_pessoa: str | None = None  # F / J
    documento: str | None = None  # CPF (11) ou CNPJ (14), só dígitos
    nome_sancionado: str | None = None
    razao_social: str | None = None
    categoria: str | None = None
    data_inicio: str | None = None  # ISO
    data_fim: str | None = None
    orgao_sancionador: str | None = None
    uf_orgao: str | None = None
    abrangencia: str | None = None
    fundamentacao: str | None = None
    raw: dict = Field(default_factory=dict)

    @classmethod
    def from_portal(cls, row: dict, fonte: str) -> "Sancao":
        return cls(
            fonte=fonte,
            tipo_pessoa=_coluna(row, "TIPO DE PESSOA"),
            documento=_so_digitos(_coluna(row, "CPF OU CNPJ")),
            nome_sancionado=_coluna(row, "NOME DO SANCIONADO"),
            razao_social=_coluna(row, "RAZAO SOCIAL"),
            categoria=_coluna(row, "CATEGORIA DA SANCAO"),
            data_inicio=parse_data_br(_coluna(row, "DATA INICIO")),
            data_fim=parse_data_br(_coluna(row, "DATA FINAL")),
            orgao_sancionador=_coluna(row, "ORGAO SANCIONADOR"),
            uf_orgao=_coluna(row, "UF ORGAO"),
            abrangencia=_coluna(row, "ABRAG"),  # cabeçalho traz 'ABRAGÊNCIA'
            fundamentacao=_coluna(row, "FUNDAMENTACAO LEGAL"),
            raw=row,
        )


class Doacao(BaseModel):
    """
    Uma doação de campanha (receita de candidato) do TSE — Etapa 8.

    O que interessa: o **doador** (CPF/CNPJ + nome) e o **donatário** (candidato,
    cargo, município). O CPF do doador-pessoa vem completo no TSE, então casa com
    sócio pelo núcleo de 6 dígitos + nome (mesma técnica das outras etapas).
    """

    ano_eleicao: str | None = None
    municipio: str | None = None  # NM_UE (município do candidato)
    cargo: str | None = None  # Prefeito / Vereador
    candidato: str | None = None
    partido: str | None = None
    doador_documento: str | None = None  # CPF (11) ou CNPJ (14), só dígitos
    doador_nome: str | None = None
    doador_cnae: str | None = None
    valor: float | None = None
    data: str | None = None  # ISO
    raw: dict = Field(default_factory=dict)

    @classmethod
    def from_tse(cls, row: dict) -> "Doacao":
        return cls(
            ano_eleicao=row.get("AA_ELEICAO"),
            municipio=row.get("NM_UE"),
            cargo=row.get("DS_CARGO"),
            candidato=row.get("NM_CANDIDATO"),
            partido=row.get("SG_PARTIDO"),
            doador_documento=_so_digitos(row.get("NR_CPF_CNPJ_DOADOR")),
            doador_nome=row.get("NM_DOADOR"),
            doador_cnae=row.get("DS_CNAE_DOADOR"),
            valor=parse_valor_br(row.get("VR_RECEITA")),
            data=parse_data_br(row.get("DT_RECEITA")),
            raw=row,
        )
