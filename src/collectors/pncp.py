"""
Coletor de contratos do PNCP — Etapa 1.

Princípio de ouro do projeto: **buscar** (HTTP) e **parsear** (função pura)
ficam separados. Os testes rodam só sobre o parser, com uma fixture salva,
sem tocar na internet.

Há duas fontes no PNCP:
  - **search API** (`config.PNCP_SEARCH_URL`): rápida, filtra Barretos por
    `municipio_id` e traz quase tudo (valor, modalidade, objeto, órgão, datas).
    Não traz o fornecedor vencedor. É a fonte primária de descoberta.
  - **consulta API** (`config.PNCP_CONSULTA_URL`): detalhe completo de cada
    contrato, incluindo o fornecedor. Usada para *enriquecer*. Sofre quedas
    (HTTP 504), então o enriquecimento é resiliente: falhou, segue sem ele.

Uso pela linha de comando:
    python -m src.collectors.pncp --paginas 3
"""

from __future__ import annotations

import argparse
import sqlite3
import time

import httpx

import config
from src.db import init_db
from src.models import Contrato, _so_digitos

_HEADERS = {"User-Agent": "observatorio-barretos/0.1", "Accept": "application/json"}


# ---------------------------------------------------------------------------
# BUSCA (HTTP) — não testada offline
# ---------------------------------------------------------------------------
def _get_com_retry(
    client: httpx.Client, url: str, params: dict | None, tentativas: int = 4
) -> httpx.Response | None:
    """GET com backoff exponencial. Tolera 504/timeout (PNCP cai com frequência)."""
    espera = 2.0
    for n in range(tentativas):
        try:
            r = client.get(url, params=params, headers=_HEADERS, timeout=60)
            if r.status_code == 200:
                return r
            # 504/502/500: servidor sobrecarregado — espera e tenta de novo.
            if r.status_code in (500, 502, 503, 504):
                time.sleep(espera)
                espera *= 2
                continue
            r.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError):
            time.sleep(espera)
            espera *= 2
    return None


def buscar_pncp(
    municipio_id: str = config.PNCP_MUNICIPIO_ID,
    paginas: int = 3,
    tam_pagina: int = 50,
) -> list[dict]:
    """
    Busca contratos de Barretos na search API do PNCP (paginado).

    Retorna a lista bruta de `items` (dicts), que vai para `parsear_pncp`.
    """
    itens: list[dict] = []
    with httpx.Client() as client:
        for pagina in range(1, paginas + 1):
            params = {
                "tipos_documento": "contrato",
                "ordenacao": "-data",
                "status": "todos",
                "municipios": municipio_id,
                "pagina": pagina,
                "tam_pagina": tam_pagina,
            }
            r = _get_com_retry(client, config.PNCP_SEARCH_URL, params)
            if r is None:
                print(f"  [aviso] página {pagina} falhou (PNCP indisponível); parando.")
                break
            lote = r.json().get("items", [])
            if not lote:
                break
            itens.extend(lote)
    return itens


def enriquecer_fornecedor(contrato: Contrato, client: httpx.Client | None = None) -> Contrato:
    """
    Preenche fornecedor_cnpj/nome consultando o detalhe na consulta API. **BÔNUS.**

    IMPORTANTE — estratégia de fornecedor:
    A fonte PRIMÁRIA do fornecedor é o **TCE-SP** (Etapa 2A traz id_fornecedor com
    CNPJ; 2B traz a parte contratada). Este enriquecimento via PNCP é apenas um
    bônus para quando a consulta API estiver no ar. NÃO transformar isto em
    fila/retry elaborado esperando o PNCP normalizar — a Etapa 2 já preenche
    fornecedor por uma fonte independente. Por isso aqui usamos poucas tentativas.

    Deriva o caminho a partir de `id_origem` (= item_url '/contratos/CNPJ/ANO/SEQ').
    É resiliente: se a consulta API estiver fora (504), devolve o contrato
    inalterado. Não levanta exceção.
    """
    if not contrato.id_origem:
        return contrato
    partes = contrato.id_origem.strip("/").split("/")
    # espera ['contratos', CNPJ, ANO, SEQ]
    if len(partes) < 4:
        return contrato
    _, cnpj, ano, seq = partes[0], partes[1], partes[2], partes[3]
    url = f"{config.PNCP_CONSULTA_URL}/v1/orgaos/{cnpj}/contratos/{ano}/{seq}"

    proprio = client is None
    client = client or httpx.Client()
    try:
        r = _get_com_retry(client, url, None, tentativas=2)
        if r is not None:
            det = r.json()
            contrato.fornecedor_cnpj = _so_digitos(det.get("niFornecedor"))
            contrato.fornecedor_nome = det.get("nomeRazaoSocialFornecedor")
    except Exception as e:  # noqa: BLE001 — enriquecimento nunca derruba a coleta
        print(f"  [aviso] enriquecimento falhou para {contrato.id}: {e!r}")
    finally:
        if proprio:
            client.close()
    return contrato


# ---------------------------------------------------------------------------
# PARSE (função pura) — testada offline sobre fixture
# ---------------------------------------------------------------------------
def parsear_pncp(payload: dict, municipio_ibge: str = config.CODIGO_IBGE) -> list[Contrato]:
    """
    Função pura: recebe a resposta JSON da search API e devolve Contratos.

    Não acessa a internet. É o que os testes exercitam.
    """
    itens = payload.get("items", [])
    contratos: list[Contrato] = []
    for item in itens:
        if not item.get("numero_controle_pncp"):
            continue  # sem chave de deduplicação, ignora
        contratos.append(Contrato.from_pncp_search(item, municipio_ibge=municipio_ibge))
    return contratos


# ---------------------------------------------------------------------------
# PERSISTÊNCIA
# ---------------------------------------------------------------------------
def salvar_contratos(conn: sqlite3.Connection, contratos: list[Contrato]) -> int:
    """
    Grava (upsert) os contratos, deduplicando por `id`.

    Inserir o mesmo contrato de novo atualiza os campos (útil quando o
    enriquecimento de fornecedor roda depois) sem criar duplicata.
    Retorna a quantidade de contratos processados.
    """
    sql = """
    INSERT INTO contratos
        (id, fonte, id_origem, orgao, orgao_cnpj, objeto, modalidade,
         fornecedor_cnpj, fornecedor_nome, valor, data, ano,
         municipio_ibge, municipio_nome, uf, raw)
    VALUES
        (:id, :fonte, :id_origem, :orgao, :orgao_cnpj, :objeto, :modalidade,
         :fornecedor_cnpj, :fornecedor_nome, :valor, :data, :ano,
         :municipio_ibge, :municipio_nome, :uf, :raw)
    ON CONFLICT(id) DO UPDATE SET
        orgao=excluded.orgao, orgao_cnpj=excluded.orgao_cnpj,
        objeto=excluded.objeto, modalidade=excluded.modalidade,
        fornecedor_cnpj=COALESCE(excluded.fornecedor_cnpj, contratos.fornecedor_cnpj),
        fornecedor_nome=COALESCE(excluded.fornecedor_nome, contratos.fornecedor_nome),
        valor=excluded.valor, data=excluded.data, ano=excluded.ano,
        municipio_nome=excluded.municipio_nome, uf=excluded.uf, raw=excluded.raw
    ;
    """
    conn.executemany(sql, [c.para_linha_db() for c in contratos])
    conn.commit()
    return len(contratos)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor de contratos do PNCP (Barretos).")
    parser.add_argument("--paginas", type=int, default=3, help="nº de páginas da search API")
    parser.add_argument("--tam-pagina", type=int, default=50, help="registros por página")
    parser.add_argument(
        "--enriquecer", action="store_true",
        help="tentar buscar o fornecedor de cada contrato (consulta API; pode estar fora)",
    )
    args = parser.parse_args()

    print(f"Buscando até {args.paginas} página(s) de contratos de Barretos no PNCP...")
    itens = buscar_pncp(paginas=args.paginas, tam_pagina=args.tam_pagina)
    contratos = parsear_pncp({"items": itens})
    print(f"  {len(contratos)} contratos parseados.")

    if args.enriquecer and contratos:
        print("  Enriquecendo fornecedores (consulta API)...")
        with httpx.Client() as client:
            for c in contratos:
                enriquecer_fornecedor(c, client=client)

    conn = init_db()
    n = salvar_contratos(conn, contratos)
    (total,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    conn.close()
    print(f"  {n} contratos gravados. Total no banco: {total}.")


if __name__ == "__main__":
    main()
