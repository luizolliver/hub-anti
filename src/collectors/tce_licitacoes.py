"""
Coletor de Licitações e Contratos do TCE-SP — Etapa 2B (Cubo Audesp Fase IV).

Este é o **lado-contrato** do TCE: o arquivo de *Ajustes* lista os contratos
firmados pelos órgãos do estado, e — ao contrário das despesas (Etapa 2A) —
traz o fornecedor contratado (CNPJ + nome). É o que permite, no futuro, o
cruzamento contrato↔fornecedor sem depender do enriquecimento do PNCP.

Como sempre no projeto, **buscar** (HTTP) e **parsear** (função pura) ficam
separados; os testes rodam só sobre `parsear_ajustes`, com uma fixture real
salva, sem tocar na internet.

Sobre as fontes:
  - Os dados vêm em ZIPs anuais (2018–2020) ou semestrais (2021–2024),
    publicados no portal de Dados Abertos do TCE-SP. Os nomes dos arquivos são
    **irregulares** ('ajustes-2019_0.zip', 'ajustes-2024-1o-semestre.zip'...),
    então o coletor **raspa os links** da página de conjuntos de dados em vez
    de chutar um padrão de URL.
  - Cada ZIP traz um CSV ';' grande (estado inteiro). Filtramos Barretos pela
    coluna 'Município'. O arquivo é UTF-8 (com BOM em alguns casos); decodifica
    com utf-8 e cai para latin-1 por segurança.

Uso pela linha de comando:
    python -m src.collectors.tce_licitacoes --anos 2019 2020
    python -m src.collectors.tce_licitacoes            # todos os anos achados
"""

from __future__ import annotations

import argparse
import csv
import io
import re
import zipfile

import httpx

import config
from src.collectors.pncp import salvar_contratos
from src.db import init_db
from src.models import Contrato

# Página de Dados Abertos que lista os conjuntos (e os links dos ZIPs).
TCE_DADOS_URL = "https://transparencia.tce.sp.gov.br/conjunto-de-dados"
# Prefixo onde os arquivos de fato moram.
TCE_ARQUIVOS_BASE = "https://transparencia.tce.sp.gov.br"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    )
}


# ---------------------------------------------------------------------------
# BUSCA (HTTP) — não testada offline
# ---------------------------------------------------------------------------
def descobrir_urls_ajustes(client: httpx.Client | None = None) -> list[str]:
    """
    Raspa a página de conjuntos de dados e devolve as URLs absolutas dos ZIPs
    de *ajustes* (uma por ano/semestre). Não chuta padrão de nome: lê o que o
    portal de fato publica.
    """
    proprio = client is None
    client = client or httpx.Client(headers=_HEADERS, timeout=120, follow_redirects=True)
    try:
        r = client.get(TCE_DADOS_URL)
        r.raise_for_status()
        html = r.text
    finally:
        if proprio:
            client.close()

    # hrefs que apontam para .../ajustes-<algo>.zip
    achados = re.findall(r'href=["\']([^"\']*ajustes[^"\']*\.zip)["\']', html, re.IGNORECASE)
    urls: list[str] = []
    for href in achados:
        if href.startswith("http"):
            url = href
        else:
            url = TCE_ARQUIVOS_BASE + ("" if href.startswith("/") else "/") + href
        if url not in urls:
            urls.append(url)
    return urls


def _ano_da_url(url: str) -> str | None:
    """Extrai o ano (AAAA) do nome do arquivo de ajustes, se houver."""
    m = re.search(r"ajustes[-_](\d{4})", url, re.IGNORECASE)
    return m.group(1) if m else None


def _ler_csv_zip(conteudo: bytes) -> list[dict]:
    """
    Abre o ZIP em memória, lê o primeiro membro e devolve as linhas como dicts.

    Trata BOM e tenta utf-8, caindo para latin-1 (alguns anos variam). Delimitador
    é ';' (padrão do Cubo Audesp).
    """
    zf = zipfile.ZipFile(io.BytesIO(conteudo))
    bruto = zf.read(zf.namelist()[0])
    if bruto[:3] == b"\xef\xbb\xbf":  # remove BOM
        bruto = bruto[3:]
    try:
        texto = bruto.decode("utf-8")
    except UnicodeDecodeError:
        texto = bruto.decode("latin-1")
    return list(csv.DictReader(io.StringIO(texto), delimiter=";"))


def buscar_ajustes(
    url: str,
    municipio: str = config.CODIGO_TCE_MUNICIPIO,
    client: httpx.Client | None = None,
) -> list[dict]:
    """
    Baixa um ZIP de ajustes e devolve as linhas (dicts) do município alvo.

    O ZIP é do estado inteiro; o filtro por 'Município' acontece aqui (lado da
    busca), para a função pura de parse não precisar varrer milhões de linhas.
    """
    proprio = client is None
    client = client or httpx.Client(headers=_HEADERS, timeout=300, follow_redirects=True)
    try:
        r = client.get(url)
        r.raise_for_status()
        linhas = _ler_csv_zip(r.content)
    finally:
        if proprio:
            client.close()

    alvo = municipio.strip().upper()
    col_mun = next(
        (c for c in (linhas[0].keys() if linhas else []) if "MUNIC" in c.upper()), None
    )
    if not col_mun:
        return []
    return [ln for ln in linhas if (ln.get(col_mun) or "").strip().upper() == alvo]


# ---------------------------------------------------------------------------
# PARSE (função pura) — testada offline sobre fixture
# ---------------------------------------------------------------------------
def parsear_ajustes(
    linhas: list[dict], municipio_ibge: str = config.CODIGO_IBGE
) -> list[Contrato]:
    """
    Função pura: recebe linhas de ajustes (nível de item) e devolve Contratos,
    **deduplicados pelo Código do Ajuste** (a chave canônica do contrato no TCE).

    Mantém a primeira linha de cada ajuste — o valor total do contrato é
    constante entre os itens do mesmo ajuste. Não acessa a internet.
    """
    vistos: set[str] = set()
    contratos: list[Contrato] = []
    for ln in linhas:
        codigo = (ln.get("Código do Ajuste") or "").strip()
        if not codigo or codigo in vistos:
            continue
        vistos.add(codigo)
        contratos.append(Contrato.from_tce_ajuste(ln, municipio_ibge=municipio_ibge))
    return contratos


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Coletor de Ajustes (contratos) do TCE-SP para Barretos."
    )
    parser.add_argument(
        "--anos", nargs="*", help="anos a coletar (ex.: 2019 2020); padrão: todos os achados"
    )
    args = parser.parse_args()

    print(f"Descobrindo arquivos de ajustes em {TCE_DADOS_URL} ...")
    urls = descobrir_urls_ajustes()
    if args.anos:
        alvo = set(args.anos)
        urls = [u for u in urls if _ano_da_url(u) in alvo]
    if not urls:
        print("  Nenhum arquivo de ajustes encontrado para os anos pedidos.")
        return
    print(f"  {len(urls)} arquivo(s) a baixar.")

    conn = init_db()
    total_grav = 0
    for url in urls:
        ano = _ano_da_url(url) or "?"
        print(f"  [{ano}] baixando {url.rsplit('/', 1)[-1]} ...")
        try:
            linhas = buscar_ajustes(url)
        except Exception as e:  # noqa: BLE001 — um ano fora não derruba os demais
            print(f"    [aviso] falhou: {e!r}")
            continue
        contratos = parsear_ajustes(linhas)
        n = salvar_contratos(conn, contratos)
        total_grav += n
        print(f"    {len(linhas)} linhas Barretos -> {n} ajustes distintos gravados.")

    (total,) = conn.execute("SELECT COUNT(*) FROM contratos;").fetchone()
    (tce,) = conn.execute("SELECT COUNT(*) FROM contratos WHERE fonte='TCE-SP';").fetchone()
    conn.close()
    print(f"\n  {total_grav} ajustes processados. Contratos no banco: {total} (TCE-SP: {tce}).")


if __name__ == "__main__":
    main()
