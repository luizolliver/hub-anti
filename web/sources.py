"""
Links para a fonte oficial (camada de apresentação).

Monta URLs públicas a partir dos identificadores que JÁ estão no banco
(`id_origem`, `fonte`, documento sancionado). Não acessa a rede nem altera a
camada de dados — só transforma IDs em links rastreáveis.

Cada link declara seu `tipo`, para a UI ser honesta sobre o que ele abre:
  - "registro" → permalink do documento específico (ex.: contrato no PNCP);
  - "busca"    → busca pré-preenchida pelo documento/nome na fonte;
  - "portal"   → página da fonte (sem deep link por registro disponível).
"""

from __future__ import annotations

import re
from urllib.parse import quote


def contrato_link(fonte: str | None, id_origem: str | None) -> dict | None:
    """
    Link do contrato na fonte.

    - PNCP: permalink do contrato — `.../app/contratos/{cnpj}/{ano}/{seq}`
      (o sequencial na UI do PNCP tem 6 dígitos). `id_origem` já vem como
      `/contratos/{cnpj}/{ano}/{seq}`.
    - TCE-SP: não há permalink por ajuste; aponta para o Portal da
      Transparência Municipal do TCE-SP (fonte, não o documento em si).
    """
    fonte = (fonte or "").strip()
    if fonte == "PNCP" and id_origem:
        partes = id_origem.strip("/").split("/")
        if len(partes) == 4 and partes[0] == "contratos":
            _, cnpj, ano, seq = partes
            seq = re.sub(r"\D", "", seq).zfill(6)
            return {
                "url": f"https://pncp.gov.br/app/contratos/{cnpj}/{ano}/{seq}",
                "label": "Ver no PNCP",
                "tipo": "registro",
            }
    if fonte.startswith("TCE"):
        return {
            "url": "https://transparencia.tce.sp.gov.br/",
            "label": "Portal TCE-SP",
            "tipo": "portal",
        }
    return None


def sancao_link(
    fonte: str | None, documento: str | None = None, nome: str | None = None
) -> dict | None:
    """
    Link da sanção no Portal da Transparência (CEIS/CNEP).

    Não guardamos o id interno da sanção, então abrimos a busca do portal
    pré-preenchida pelo documento do sancionado (CPF/CNPJ) ou, na falta dele,
    pelo nome — o usuário confirma o registro na fonte.
    """
    fonte = (fonte or "").strip() or "Portal da Transparência"
    termo = re.sub(r"\D", "", documento or "") or (nome or "").strip()
    if termo:
        return {
            "url": f"https://portaldatransparencia.gov.br/busca?termo={quote(termo)}",
            "label": f"Buscar na fonte ({fonte})",
            "tipo": "busca",
        }
    return {
        "url": "https://portaldatransparencia.gov.br/sancoes/consulta",
        "label": "Consulta de sanções",
        "tipo": "portal",
    }
