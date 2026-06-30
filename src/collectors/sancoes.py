"""
Camada de integridade — sanções (Etapa 5).

Baixa CEIS (inidôneas/suspensas) e CNEP (Lei Anticorrupção) do Portal da
Transparência federal e cruza cada sanção contra os `fornecedores` e os
`socios` de Barretos. Só os **cruzamentos encontrados** são gravados
(`sancoes_encontradas`) — não o cadastro inteiro de ~25 mil sanções.

Tipos de casamento:
  - **CNPJ exato** → fornecedor sancionado, ou sócio PJ sancionado.
  - **CPF (núcleo de 6 díg. + nome)** → sócio pessoa física sancionado. O CEIS
    traz o CPF completo; o sócio tem o CPF mascarado — ambos reduzem ao mesmo
    núcleo (ver `cpf_nucleo`/`nivel_vinculo_socio`).

Também calcula a **idade da empresa** numa data (base para a bandeira de
empresa recém-aberta, Etapa 6).

A Relação de Apenados do TCE-SP (sem download em massa) fica para uma
sub-etapa de raspagem dedicada.

Uso:
    python -m src.collectors.sancoes
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import io
import sqlite3
import time
import zipfile

import httpx

from src.db import init_db
from src.models import Sancao
from src.normalize.entidades import cpf_nucleo, idade_empresa_meses, nivel_vinculo_socio

__all__ = ["buscar_ceis", "buscar_cnep", "parsear_sancoes", "cruzar_sancoes",
           "ler_csv_sancoes", "idade_empresa_meses"]

_PORTAL = "https://portaldatransparencia.gov.br/download-de-dados"
# O Portal usa um WAF que exige cabeçalhos de navegador.
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept": "*/*",
    "Referer": "https://portaldatransparencia.gov.br/download-de-dados",
}


# ---------------------------------------------------------------------------
# BUSCA (HTTP) — baixa o ZIP do dia (com fallback para dias anteriores)
# ---------------------------------------------------------------------------
def _baixar(tipo: str, dias_tentativa: int = 10) -> tuple[list[dict], datetime.date | None]:
    """
    Baixa o CSV de sanções (`tipo` = 'ceis' ou 'cnep') do Portal e devolve as
    linhas como dicts. O arquivo do dia pode ainda não existir; tenta dias
    anteriores. Retorna ([], None) se nada for obtido.
    """
    hoje = datetime.date.today()
    with httpx.Client(follow_redirects=True, timeout=120) as client:
        for delta in range(dias_tentativa):
            d = hoje - datetime.timedelta(days=delta)
            url = f"{_PORTAL}/{tipo}/{d.strftime('%Y%m%d')}"
            # O Portal devolve 202 ("Accepted") quando está montando o arquivo ou
            # nos throttlando; o 200 com o ZIP costuma vir numa nova tentativa.
            espera = 3.0
            for _ in range(3):
                try:
                    r = client.get(url, headers=_HEADERS)
                except (httpx.TimeoutException, httpx.TransportError):
                    break
                if r.status_code == 200 and len(r.content) > 1000:
                    try:
                        zf = zipfile.ZipFile(io.BytesIO(r.content))
                        texto = zf.read(zf.namelist()[0]).decode("latin-1")
                        return ler_csv_sancoes(texto), d
                    except zipfile.BadZipFile:
                        break  # arquivo desse dia não serve; tenta o dia anterior
                if r.status_code in (202, 429, 500, 502, 503):
                    time.sleep(espera)
                    espera *= 2
                    continue
                break  # 403/404/405: arquivo do dia indisponível; tenta dia anterior
    return [], None


def ler_csv_sancoes(texto: str) -> list[dict]:
    """Lê o CSV (delimitado por ';') das sanções em uma lista de dicts. Puro."""
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def buscar_ceis() -> list[dict]:
    rows, _ = _baixar("ceis")
    return rows


def buscar_cnep() -> list[dict]:
    rows, _ = _baixar("cnep")
    return rows


# ---------------------------------------------------------------------------
# PARSE (função pura) — testada offline
# ---------------------------------------------------------------------------
def parsear_sancoes(rows: list[dict], fonte: str) -> list[Sancao]:
    """Linhas brutas do Portal → lista de `Sancao`. Sem rede."""
    return [Sancao.from_portal(r, fonte) for r in rows]


# ---------------------------------------------------------------------------
# CRUZAMENTO
# ---------------------------------------------------------------------------
def _registrar(achados: list[dict], *, alvo_tipo, alvo_cnpj, alvo_nome, vinculo, s: Sancao) -> None:
    chave = f"{alvo_tipo}|{alvo_cnpj}|{s.fonte}|{s.documento}|{s.data_inicio}|{s.categoria}"
    achados.append(
        {
            "id": hashlib.sha1(chave.encode("utf-8")).hexdigest(),
            "alvo_tipo": alvo_tipo,
            "alvo_cnpj": alvo_cnpj,
            "alvo_nome": alvo_nome,
            "vinculo": vinculo,
            "fonte": s.fonte,
            "documento_sancionado": s.documento,
            "nome_sancionado": s.nome_sancionado,
            "categoria": s.categoria,
            "data_inicio": s.data_inicio,
            "data_fim": s.data_fim,
            "orgao_sancionador": s.orgao_sancionador,
            "abrangencia": s.abrangencia,
            "fundamentacao": s.fundamentacao,
            "raw": None,
        }
    )


def cruzar_sancoes(conn: sqlite3.Connection, sancoes: list[Sancao]) -> list[dict]:
    """
    Cruza as sanções contra fornecedores e sócios. Devolve os achados (dicts) e
    os grava em `sancoes_encontradas` (dedup por id). Não grava o cadastro
    completo de sanções.
    """
    achados: list[dict] = []
    for s in sancoes:
        doc = s.documento or ""
        if len(doc) == 14:  # CNPJ
            forn = conn.execute(
                "SELECT cnpj, nome FROM fornecedores WHERE cnpj = ?", (doc,)
            ).fetchone()
            if forn:
                _registrar(achados, alvo_tipo="fornecedor", alvo_cnpj=forn["cnpj"],
                           alvo_nome=forn["nome"], vinculo="cnpj", s=s)
            for soc in conn.execute(
                "SELECT cnpj_empresa, nome_socio FROM socios WHERE cnpj_socio = ?", (doc,)
            ):
                _registrar(achados, alvo_tipo="socio_pj", alvo_cnpj=soc["cnpj_empresa"],
                           alvo_nome=soc["nome_socio"], vinculo="cnpj", s=s)
        elif len(doc) == 11:  # CPF — casa sócio por núcleo + nome
            nucleo = cpf_nucleo(doc)
            if not nucleo:
                continue
            for soc in conn.execute(
                "SELECT cnpj_empresa, nome_socio, documento_socio "
                "FROM socios WHERE documento_visivel = ?",
                (nucleo,),
            ):
                vinc = nivel_vinculo_socio(
                    s.nome_sancionado, doc, soc["nome_socio"], soc["documento_socio"]
                )
                if vinc in ("forte", "investigar"):
                    _registrar(achados, alvo_tipo="socio_pf", alvo_cnpj=soc["cnpj_empresa"],
                               alvo_nome=soc["nome_socio"], vinculo=vinc, s=s)

    if achados:
        conn.executemany(
            """
            INSERT OR REPLACE INTO sancoes_encontradas
                (id, alvo_tipo, alvo_cnpj, alvo_nome, vinculo, fonte,
                 documento_sancionado, nome_sancionado, categoria, data_inicio,
                 data_fim, orgao_sancionador, abrangencia, fundamentacao, raw)
            VALUES
                (:id, :alvo_tipo, :alvo_cnpj, :alvo_nome, :vinculo, :fonte,
                 :documento_sancionado, :nome_sancionado, :categoria, :data_inicio,
                 :data_fim, :orgao_sancionador, :abrangencia, :fundamentacao, :raw)
            """,
            achados,
        )
        conn.commit()
    return achados


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    conn = init_db()
    total = 0
    for tipo, buscar in (("CEIS", buscar_ceis), ("CNEP", buscar_cnep)):
        print(f"Baixando {tipo}...")
        rows = buscar()
        sancoes = parsear_sancoes(rows, tipo)
        achados = cruzar_sancoes(conn, sancoes)
        total += len(achados)
        print(f"  {len(sancoes)} sanções; {len(achados)} cruzamentos com Barretos.")

    print(f"\nTotal de cruzamentos: {total}")
    for r in conn.execute(
        "SELECT alvo_tipo, alvo_nome, fonte, categoria FROM sancoes_encontradas "
        "ORDER BY alvo_tipo LIMIT 20"
    ):
        print(f"  [{r['fonte']}/{r['alvo_tipo']}] {(r['alvo_nome'] or '')[:34]:34} | {r['categoria']}")
    conn.close()


if __name__ == "__main__":
    main()
