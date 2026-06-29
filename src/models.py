"""
Modelos de dados (pydantic) do Observatório.

Por enquanto há apenas o `Contrato`, o registro canônico unificado que
recebe dados tanto do PNCP (Etapa 1) quanto do TCE-SP (Etapa 2). Manter o
modelo único desde já evita retrabalho na reconciliação (Etapa 3).
"""

from __future__ import annotations

import json
import re

from pydantic import BaseModel, Field


def _so_digitos(valor: str | None) -> str | None:
    """Mantém apenas os dígitos de um documento (CNPJ/CPF). None se vazio."""
    if not valor:
        return None
    digitos = re.sub(r"\D", "", valor)
    return digitos or None


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
