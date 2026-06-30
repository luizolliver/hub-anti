"""
Doações de campanha (TSE) — Etapa 8.

A ligação político-empresa **com nexo** (substitui a ideia falha de "autor de
lei"): casa o **doador** de campanha com os **sócios** dos fornecedores e o
**donatário** com os candidatos de Barretos. Marca o fornecedor cujo sócio
doou para um candidato local.

Fonte: dados abertos do TSE (receitas de candidatos, por ano de eleição/UF). O
arquivo é um ZIP nacional de ~1,2 GB com um CSV por UF; usamos **range requests**
(`remotezip`) para ler só o membro de SP, e filtramos Barretos em streaming.

Casamento (mesma técnica robusta das outras etapas):
  - doador PF: CPF vem COMPLETO no TSE → núcleo de 6 dígitos + nome casa com o
    sócio (CPF mascarado). Níveis forte/investigar (`nivel_vinculo_socio`).
  - doador PJ: CNPJ casa exato com `fornecedores` (doação empresarial é proibida
    desde 2015; na prática são partidos/candidatos).

⚠️ Limite honesto: casamento por nome é falível (homônimos) — os 6 dígitos do
CPF reduzem muito o risco, mas a saída é **pista a confirmar**, não prova. E
identificamos o candidato de Barretos (donatário), não necessariamente o
*eleito* (isso exigiria o arquivo de resultados).

Uso:
    python -m src.collectors.tse --ano 2024
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import sqlite3

from src.db import init_db
from src.models import Doacao
from src.normalize.entidades import cpf_nucleo, nivel_vinculo_socio

_ZIP_URL = (
    "https://cdn.tse.jus.br/estatistica/sead/odsele/prestacao_contas/"
    "prestacao_de_contas_eleitorais_candidatos_{ano}.zip"
)
_MEMBRO = "receitas_candidatos_{ano}_{uf}.csv"


# ---------------------------------------------------------------------------
# BUSCA (HTTP, via range) — filtra o município em streaming
# ---------------------------------------------------------------------------
def buscar_receitas(ano: int = 2024, uf: str = "SP", municipio: str = "BARRETOS") -> list[dict]:
    """
    Lê via range requests só o CSV de receitas da UF dentro do ZIP nacional e
    devolve as linhas cujo donatário é do `municipio` (NM_UE). Evita baixar 1,2 GB.
    """
    from remotezip import RemoteZip

    url = _ZIP_URL.format(ano=ano)
    membro = _MEMBRO.format(ano=ano, uf=uf)
    alvo = (municipio or "").strip().upper()
    linhas: list[dict] = []
    with RemoteZip(url) as zf:
        with zf.open(membro) as f:
            wrapper = io.TextIOWrapper(f, encoding="latin-1", newline="")
            for row in csv.DictReader(wrapper, delimiter=";"):
                if (row.get("NM_UE") or "").strip().upper() == alvo:
                    linhas.append(row)
    return linhas


def ler_csv_receitas(texto: str) -> list[dict]:
    """Lê um CSV de receitas (delimitado por ';') em lista de dicts. Puro."""
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


# ---------------------------------------------------------------------------
# PARSE (função pura)
# ---------------------------------------------------------------------------
def parsear_doacoes(rows: list[dict]) -> list[Doacao]:
    """Linhas brutas do TSE → lista de `Doacao`. Sem rede."""
    return [Doacao.from_tse(r) for r in rows]


# ---------------------------------------------------------------------------
# CRUZAMENTO
# ---------------------------------------------------------------------------
def _registrar(achados, *, alvo_tipo, alvo_cnpj, alvo_nome, vinculo, d: Doacao):
    chave = f"{alvo_tipo}|{alvo_cnpj}|{d.doador_documento}|{d.candidato}|{d.data}|{d.valor}"
    achados.append(
        {
            "id": hashlib.sha1(chave.encode("utf-8")).hexdigest(),
            "alvo_tipo": alvo_tipo,
            "alvo_cnpj": alvo_cnpj,
            "alvo_nome": alvo_nome,
            "vinculo": vinculo,
            "doador_documento": d.doador_documento,
            "doador_nome": d.doador_nome,
            "candidato": d.candidato,
            "cargo": d.cargo,
            "partido": d.partido,
            "municipio": d.municipio,
            "ano_eleicao": d.ano_eleicao,
            "valor": d.valor,
            "data": d.data,
            "raw": None,
        }
    )


def cruzar_doacoes(conn: sqlite3.Connection, doacoes: list[Doacao]) -> list[dict]:
    """
    Cruza as doações contra sócios (doador PF) e fornecedores (doador PJ) e grava
    em `doacoes_relacionadas`. Devolve os achados.
    """
    achados: list[dict] = []
    for d in doacoes:
        doc = d.doador_documento or ""
        if len(doc) == 11:  # doador pessoa física → casa com sócio
            nucleo = cpf_nucleo(doc)
            if not nucleo:
                continue
            for soc in conn.execute(
                "SELECT cnpj_empresa, nome_socio, documento_socio "
                "FROM socios WHERE documento_visivel = ?",
                (nucleo,),
            ):
                vinc = nivel_vinculo_socio(
                    d.doador_nome, doc, soc["nome_socio"], soc["documento_socio"]
                )
                if vinc in ("forte", "investigar"):
                    _registrar(achados, alvo_tipo="socio", alvo_cnpj=soc["cnpj_empresa"],
                               alvo_nome=soc["nome_socio"], vinculo=vinc, d=d)
        elif len(doc) == 14:  # doador PJ → casa com fornecedor
            forn = conn.execute(
                "SELECT cnpj, nome FROM fornecedores WHERE cnpj = ?", (doc,)
            ).fetchone()
            if forn:
                _registrar(achados, alvo_tipo="fornecedor", alvo_cnpj=forn["cnpj"],
                           alvo_nome=forn["nome"], vinculo="cnpj", d=d)

    if achados:
        conn.executemany(
            """
            INSERT OR REPLACE INTO doacoes_relacionadas
                (id, alvo_tipo, alvo_cnpj, alvo_nome, vinculo, doador_documento,
                 doador_nome, candidato, cargo, partido, municipio, ano_eleicao,
                 valor, data, raw)
            VALUES
                (:id, :alvo_tipo, :alvo_cnpj, :alvo_nome, :vinculo, :doador_documento,
                 :doador_nome, :candidato, :cargo, :partido, :municipio, :ano_eleicao,
                 :valor, :data, :raw)
            """,
            achados,
        )
        conn.commit()
    return achados


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Doações de campanha (TSE) — Barretos.")
    parser.add_argument("--ano", type=int, default=2024, help="ano da eleição (2024 = municipal)")
    parser.add_argument("--uf", default="SP")
    parser.add_argument("--municipio", default="BARRETOS")
    args = parser.parse_args()

    print(f"Lendo receitas {args.uf} {args.ano} (filtrando {args.municipio})...")
    rows = buscar_receitas(args.ano, args.uf, args.municipio)
    doacoes = parsear_doacoes(rows)
    print(f"  {len(doacoes)} doações a candidatos de {args.municipio}.")

    conn = init_db()
    achados = cruzar_doacoes(conn, doacoes)
    print(f"  {len(achados)} doações ligadas a fornecedores/sócios de Barretos.")
    for r in conn.execute(
        "SELECT alvo_tipo, doador_nome, candidato, cargo, valor FROM doacoes_relacionadas "
        "ORDER BY valor DESC LIMIT 20"
    ):
        print(f"  [{r['alvo_tipo']}] {(r['doador_nome'] or '')[:26]:26} -> "
              f"{(r['candidato'] or '')[:24]:24} ({r['cargo']}) R$ {r['valor']:,.2f}")
    conn.close()


if __name__ == "__main__":
    main()
