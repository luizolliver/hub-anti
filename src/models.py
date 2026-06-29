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
