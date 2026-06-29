"""
Enriquecimento societário (CNPJ/QSA) — Etapa 4.

Para cada CNPJ em `fornecedores`, busca o cadastro e o quadro de sócios na
BrasilAPI e grava em `empresas` e `socios`. Responde "quem é dono" de cada
empresa que recebe dinheiro público — base da rede societária (Etapa 7) e das
bandeiras de empresa nova / sócio sancionado (Etapas 5–6).

Cuidados (pedidos pelo blueprint):
  - **Cache**: não rebusca um CNPJ já consultado nos últimos N dias.
  - **Limite de requisições**: pausa entre chamadas e backoff em 429/5xx.
  - **busca** (HTTP) separada de **parse** (função pura, testada offline).

⚠️ O CPF dos sócios vem MASCARADO pela Receita ('***234078**'). Logo, casar
"mesma pessoa" entre empresas é por NOME (fuzzy) — pista fraca, não chave.

Uso pela linha de comando:
    python -m src.collectors.cnpj --limite 50
"""

from __future__ import annotations

import argparse
import sqlite3
import time

import httpx

from src.db import init_db
from src.models import Empresa, Socio

_HEADERS = {"User-Agent": "observatorio-barretos/0.1", "Accept": "application/json"}
_BRASILAPI = "https://brasilapi.com.br/api/cnpj/v1"

# Pausa educada entre requisições (a BrasilAPI é gratuita; não vamos martelar).
_PAUSA_SEG = 0.5


# ---------------------------------------------------------------------------
# BUSCA (HTTP)
# ---------------------------------------------------------------------------
def buscar_cnpj(cnpj: str, client: httpx.Client, tentativas: int = 4) -> dict | None:
    """
    Busca o cadastro + QSA de um CNPJ na BrasilAPI.

    Retorna o JSON (dict) ou None se falhar. Faz backoff em 429 (limite) e 5xx.
    """
    url = f"{_BRASILAPI}/{cnpj}"
    espera = 2.0
    for _ in range(tentativas):
        try:
            r = client.get(url, headers=_HEADERS, timeout=40)
            if r.status_code == 200:
                return r.json()
            if r.status_code == 404:
                return None  # CNPJ inexistente na base — não adianta repetir
            if r.status_code in (429, 500, 502, 503, 504):
                time.sleep(espera)
                espera *= 2
                continue
            r.raise_for_status()
        except (httpx.TimeoutException, httpx.TransportError):
            time.sleep(espera)
            espera *= 2
    return None


# ---------------------------------------------------------------------------
# PARSE (funções puras) — testadas offline
# ---------------------------------------------------------------------------
def parsear_empresa(payload: dict) -> Empresa:
    """Função pura: JSON da BrasilAPI → Empresa."""
    return Empresa.from_brasilapi(payload)


def parsear_socios(payload: dict, cnpj_empresa: str) -> list[Socio]:
    """Função pura: extrai os sócios do QSA."""
    return [Socio.from_qsa(s, cnpj_empresa) for s in payload.get("qsa", []) or []]


# ---------------------------------------------------------------------------
# PERSISTÊNCIA + CACHE
# ---------------------------------------------------------------------------
def precisa_atualizar(conn: sqlite3.Connection, cnpj: str, dias: int = 30) -> bool:
    """
    True se o CNPJ ainda não foi consultado ou foi há mais de `dias` dias.
    Evita rebuscar o mesmo CNPJ (cache local).
    """
    row = conn.execute(
        "SELECT julianday('now') - julianday(atualizado_em) AS idade "
        "FROM empresas WHERE cnpj = ?",
        (cnpj,),
    ).fetchone()
    if row is None or row["idade"] is None:
        return True
    return row["idade"] > dias


def salvar_empresa(conn: sqlite3.Connection, empresa: Empresa) -> None:
    """Grava/atualiza a empresa e renova o carimbo de atualização."""
    linha = empresa.para_linha_db()
    cols = [c for c in linha if c != "atualizado_em"]
    placeholders = ", ".join(f":{c}" for c in cols)
    updates = ", ".join(f"{c}=excluded.{c}" for c in cols)
    conn.execute(
        f"INSERT INTO empresas ({', '.join(cols)}, atualizado_em) "
        f"VALUES ({placeholders}, datetime('now')) "
        f"ON CONFLICT(cnpj) DO UPDATE SET {updates}, atualizado_em=datetime('now')",
        linha,
    )
    conn.commit()


def salvar_socios(conn: sqlite3.Connection, cnpj_empresa: str, socios: list[Socio]) -> None:
    """Regrava os sócios da empresa (apaga os antigos e insere os atuais)."""
    conn.execute("DELETE FROM socios WHERE cnpj_empresa = ?", (cnpj_empresa,))
    if socios:
        conn.executemany(
            """
            INSERT OR IGNORE INTO socios
                (id, cnpj_empresa, nome_socio, nome_socio_chave, documento_socio,
                 documento_visivel, cnpj_socio, tipo_socio, qualificacao,
                 data_entrada, faixa_etaria, raw)
            VALUES
                (:id, :cnpj_empresa, :nome_socio, :nome_socio_chave, :documento_socio,
                 :documento_visivel, :cnpj_socio, :tipo_socio, :qualificacao,
                 :data_entrada, :faixa_etaria, :raw)
            """,
            [s.para_linha_db() for s in socios],
        )
    conn.commit()


# ---------------------------------------------------------------------------
# ORQUESTRAÇÃO
# ---------------------------------------------------------------------------
def enriquecer(conn: sqlite3.Connection, limite: int | None = None, dias_cache: int = 30) -> dict:
    """
    Percorre os CNPJs de `fornecedores` que precisam de atualização e os
    enriquece. Retorna um resumo {consultados, empresas, socios, falhas}.
    """
    cnpjs = [r["cnpj"] for r in conn.execute("SELECT cnpj FROM fornecedores ORDER BY valor_pago DESC")]
    alvos = [c for c in cnpjs if precisa_atualizar(conn, c, dias_cache)]
    if limite is not None:
        alvos = alvos[:limite]

    resumo = {"consultados": 0, "empresas": 0, "socios": 0, "falhas": 0}
    with httpx.Client() as client:
        for cnpj in alvos:
            resumo["consultados"] += 1
            payload = buscar_cnpj(cnpj, client)
            if not payload:
                resumo["falhas"] += 1
                continue
            empresa = parsear_empresa(payload)
            socios = parsear_socios(payload, cnpj)
            salvar_empresa(conn, empresa)
            salvar_socios(conn, cnpj, socios)
            resumo["empresas"] += 1
            resumo["socios"] += len(socios)
            time.sleep(_PAUSA_SEG)
    return resumo


def main() -> None:
    parser = argparse.ArgumentParser(description="Enriquecimento societário (CNPJ/QSA).")
    parser.add_argument("--limite", type=int, default=20, help="máx. de CNPJs por execução")
    parser.add_argument("--dias-cache", type=int, default=30, help="não rebuscar antes de N dias")
    args = parser.parse_args()

    conn = init_db()
    print(f"Enriquecendo até {args.limite} fornecedores (cache de {args.dias_cache} dias)...")
    resumo = enriquecer(conn, limite=args.limite, dias_cache=args.dias_cache)
    print(
        f"  consultados={resumo['consultados']} | empresas={resumo['empresas']} | "
        f"socios={resumo['socios']} | falhas={resumo['falhas']}"
    )
    conn.close()


if __name__ == "__main__":
    main()
