"""
Coletor de Despesas do TCE-SP — Etapa 2A (fonte primária do fornecedor).

Segue o dinheiro que de fato saiu (empenhado → liquidado → pago) por
fornecedor. Diferente do PNCP, aqui o `id_fornecedor` traz o **CNPJ**, o que
torna esta a fonte primária para cruzar fornecedores nas etapas seguintes.

Estratégia em duas frentes (a 2ª virá quando precisarmos de histórico amplo):
  1. **API REST** (`/api/json/despesas/{municipio}/{ano}/{mes}`): rápida, já
     filtra Barretos pelo slug. Apesar de a documentação citar 2014–2019, na
     prática responde de **2014 até o ano corrente** (confirmado em 2026) — é o
     que este módulo usa para o histórico completo.
  2. **CSV anual em massa** (despesas-AAAA.zip, ~2 GB, todo o estado): leitura
     em streaming + filtro de Barretos. Sub-etapa futura (2008→2025).

Princípio de ouro: **buscar** (HTTP) separado de **parsear** (função pura).
Os testes rodam só sobre a fixture, offline.

Uso pela linha de comando:
    python -m src.collectors.tce_despesas --ano 2019 --meses 1-3
"""

from __future__ import annotations

import argparse
import sqlite3
import time

import httpx

import config
from src.db import init_db
from src.models import Despesa

_HEADERS = {"User-Agent": "observatorio-barretos/0.1", "Accept": "application/json"}
_TCE_REST = config.TCE_REST_URL

# Slug do município na API REST do TCE (confirmado em /api/json/municipios).
MUNICIPIO_SLUG = config.TCE_MUNICIPIO_SLUG


# ---------------------------------------------------------------------------
# BUSCA (HTTP)
# ---------------------------------------------------------------------------
def buscar_despesas(
    ano: int, mes: int, municipio: str = MUNICIPIO_SLUG, tentativas: int = 3
) -> list[dict]:
    """
    Busca as despesas de um município/ano/mês na API REST do TCE-SP.

    Retorna a lista bruta de linhas (dicts). A API já devolve apenas o município
    pedido, então não há filtro client-side a fazer aqui.
    """
    url = f"{_TCE_REST}/despesas/{municipio}/{ano}/{mes}"
    espera = 2.0
    with httpx.Client() as client:
        for _ in range(tentativas):
            try:
                r = client.get(url, headers=_HEADERS, timeout=90)
                if r.status_code == 200:
                    dados = r.json()
                    return dados if isinstance(dados, list) else []
                if r.status_code in (500, 502, 503, 504):
                    time.sleep(espera)
                    espera *= 2
                    continue
                r.raise_for_status()
            except (httpx.TimeoutException, httpx.TransportError):
                time.sleep(espera)
                espera *= 2
    print(f"  [aviso] falha ao buscar {municipio} {ano}/{mes} (TCE indisponível).")
    return []


# ---------------------------------------------------------------------------
# PARSE (função pura) — testada offline
# ---------------------------------------------------------------------------
def parsear_despesas(rows: list[dict], municipio: str = MUNICIPIO_SLUG) -> list[Despesa]:
    """Função pura: linhas brutas do TCE → lista de `Despesa`. Sem rede."""
    return [Despesa.from_tce(row, municipio=municipio) for row in rows]


# ---------------------------------------------------------------------------
# PERSISTÊNCIA
# ---------------------------------------------------------------------------
def salvar_despesas(conn: sqlite3.Connection, despesas: list[Despesa]) -> int:
    """
    Grava as despesas deduplicando por `id` (hash do conteúdo).

    Re-coletar o mesmo mês não duplica (INSERT OR IGNORE). Retorna quantas
    linhas foram efetivamente inseridas (novas).
    """
    sql = """
    INSERT OR IGNORE INTO despesas
        (id, fonte, municipio, orgao, ano, mes, evento, nr_empenho,
         fornecedor_documento, fornecedor_tipo, fornecedor_nome, data, valor, raw)
    VALUES
        (:id, :fonte, :municipio, :orgao, :ano, :mes, :evento, :nr_empenho,
         :fornecedor_documento, :fornecedor_tipo, :fornecedor_nome, :data, :valor, :raw)
    ;
    """
    antes = conn.total_changes
    conn.executemany(sql, [d.para_linha_db() for d in despesas])
    conn.commit()
    return conn.total_changes - antes


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _parse_meses(spec: str) -> list[int]:
    """Aceita '1', '1-3', '1,4,7' e devolve a lista de meses."""
    meses: list[int] = []
    for parte in spec.split(","):
        if "-" in parte:
            ini, fim = parte.split("-")
            meses.extend(range(int(ini), int(fim) + 1))
        else:
            meses.append(int(parte))
    return [m for m in meses if 1 <= m <= 12]


def main() -> None:
    parser = argparse.ArgumentParser(description="Coletor de Despesas do TCE-SP (Barretos).")
    parser.add_argument("--ano", type=int, default=2019, help="ano (REST cobre 2014 até o atual)")
    parser.add_argument("--meses", default="1", help="ex.: '1', '1-3', '1,6,12'")
    parser.add_argument("--municipio", default=MUNICIPIO_SLUG)
    args = parser.parse_args()

    conn = init_db()
    total_novas = 0
    for mes in _parse_meses(args.meses):
        rows = buscar_despesas(args.ano, mes, municipio=args.municipio)
        despesas = parsear_despesas(rows, municipio=args.municipio)
        novas = salvar_despesas(conn, despesas)
        total_novas += novas
        print(f"  {args.ano}/{mes:02d}: {len(despesas)} linhas, {novas} novas.")

    # Resumo por evento.
    print("\nResumo por evento (município, todos os anos no banco):")
    for evento, n, soma in conn.execute(
        "SELECT evento, COUNT(*), COALESCE(SUM(valor),0) FROM despesas "
        "WHERE municipio=? GROUP BY evento ORDER BY 3 DESC",
        (args.municipio,),
    ):
        print(f"  {evento:18} | {n:6} linhas | R$ {soma:,.2f}")
    conn.close()
    print(f"\nTotal de novas despesas gravadas: {total_novas}.")


if __name__ == "__main__":
    main()
