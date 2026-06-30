"""
Monitoramento contínuo — Etapa 11.

Rotina agendável (cron/Agendador de Tarefas/GitHub Actions) que:
  1. (opcional) roda os coletores principais — PNCP e o cruzamento de sanções;
  2. recalcula fornecedores e bandeiras;
  3. detecta o que é **novo** desde a última execução (contratos sinalizados e
     fornecedores que entraram/subiram no nível de atenção);
  4. gera um **alerta em Markdown** com as novidades.

O estado do que já foi alertado fica em `monitor_estado`, para não repetir.
A detecção e a geração do alerta são testáveis offline; só `coletar()` toca a
rede.

Uso:
    python -m src.monitor            # detecta novidades no banco atual
    python -m src.monitor --coletar  # roda PNCP + sanções antes de detectar
"""

from __future__ import annotations

import argparse
import datetime
import sqlite3

from src.analysis.flags import avaliar
from src.consultas import ranking_atencao
from src.db import init_db


# ---------------------------------------------------------------------------
# Coleta (rede) — opcional
# ---------------------------------------------------------------------------
def coletar(conn: sqlite3.Connection, paginas_pncp: int = 3) -> dict:
    """
    Roda os coletores principais e recalcula derivados. Toca a rede.
    Retorna um pequeno resumo. Falhas de rede são toleradas (seguimos com o
    que já há no banco).
    """
    resumo = {"contratos": 0, "sancoes": 0, "fornecedores": 0}
    try:
        from src.collectors.pncp import buscar_pncp, parsear_pncp, salvar_contratos
        itens = buscar_pncp(paginas=paginas_pncp)
        resumo["contratos"] = salvar_contratos(conn, parsear_pncp({"items": itens}))
    except Exception as e:  # noqa: BLE001 — monitor não pode quebrar por rede
        print(f"  [aviso] PNCP falhou: {e!r}")

    try:
        from src.normalize.entidades import construir_fornecedores
        resumo["fornecedores"] = construir_fornecedores(conn)
    except Exception as e:  # noqa: BLE001
        print(f"  [aviso] fornecedores: {e!r}")

    try:
        from src.collectors.sancoes import buscar_ceis, cruzar_sancoes, parsear_sancoes
        achados = cruzar_sancoes(conn, parsear_sancoes(buscar_ceis(), "CEIS"))
        resumo["sancoes"] = len(achados)
    except Exception as e:  # noqa: BLE001
        print(f"  [aviso] sanções: {e!r}")

    return resumo


# ---------------------------------------------------------------------------
# Detecção de novidades (offline, testável)
# ---------------------------------------------------------------------------
def _ja_visto(conn: sqlite3.Connection, chave: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM monitor_estado WHERE chave = ?", (chave,)
    ).fetchone() is not None


def _marcar(conn: sqlite3.Connection, chave: str, tipo: str) -> None:
    conn.execute(
        "INSERT OR IGNORE INTO monitor_estado (chave, tipo) VALUES (?, ?)", (chave, tipo)
    )


def _bandeiras_contrato(row: dict) -> list:
    """Bandeiras computáveis só com os campos do contrato (sem contexto externo)."""
    contrato = {"modalidade": row.get("modalidade"), "data": row.get("data"),
                "valor": row.get("valor")}
    return avaliar(contrato, {})["bandeiras"]


def detectar_contratos_novos(conn: sqlite3.Connection) -> list[dict]:
    """
    Contratos ainda não alertados que disparam bandeira (nível de contrato:
    dispensa/inexigibilidade, fim de exercício). Marca-os como vistos.
    """
    novos: list[dict] = []
    for row in conn.execute(
        "SELECT id, orgao, modalidade, objeto, valor, data, fornecedor_nome FROM contratos"
    ):
        d = dict(row)
        bandeiras = _bandeiras_contrato(d)
        if not bandeiras:
            continue
        chave = f"contrato:{d['id']}"
        if _ja_visto(conn, chave):
            continue
        _marcar(conn, chave, "contrato")
        novos.append({**d, "bandeiras": [b.codigo for b in bandeiras],
                      "nivel": sum(b.peso for b in bandeiras)})
    conn.commit()
    return novos


def detectar_fornecedores_novos(conn: sqlite3.Connection, minimo: int = 1) -> list[dict]:
    """
    Fornecedores que entraram no radar OU subiram de nível desde a última vez.
    A chave inclui o nível, então uma mudança de nível gera novo alerta.
    """
    novos: list[dict] = []
    for r in ranking_atencao(conn, limite=10_000, minimo=minimo):
        chave = f"fornecedor:{r['cnpj']}:{r['nivel_atencao']}"
        if _ja_visto(conn, chave):
            continue
        _marcar(conn, chave, "fornecedor")
        novos.append(r)
    conn.commit()
    return novos


# ---------------------------------------------------------------------------
# Alerta em Markdown (função pura)
# ---------------------------------------------------------------------------
def _moeda(v) -> str:
    try:
        return f"R$ {float(v):,.2f}"
    except (TypeError, ValueError):
        return "—"


def gerar_alerta_md(
    contratos_novos: list[dict], fornecedores_novos: list[dict], quando: str | None = None
) -> str:
    """Monta o alerta em Markdown a partir das novidades. Função pura."""
    quando = quando or datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    L = [f"# Alerta do Observatório — {quando}", ""]

    if not contratos_novos and not fornecedores_novos:
        L.append("_Nenhuma novidade sinalizada desde a última verificação._")
        return "\n".join(L)

    L.append(f"**{len(fornecedores_novos)}** fornecedor(es) novo(s)/que subiram de nível e "
             f"**{len(contratos_novos)}** contrato(s) novo(s) sinalizado(s).")
    L.append("")

    if fornecedores_novos:
        L.append("## Fornecedores no radar")
        for f in sorted(fornecedores_novos, key=lambda x: x["nivel_atencao"], reverse=True):
            L.append(f"- **nível {f['nivel_atencao']}** — {f['nome'] or '—'} "
                     f"(`{f['cnpj']}`, pago {_moeda(f['valor_pago'])}): "
                     f"{', '.join(f['bandeiras'])}")
        L.append("")

    if contratos_novos:
        L.append("## Contratos novos sinalizados")
        for c in sorted(contratos_novos, key=lambda x: x["nivel"], reverse=True):
            obj = (c.get("objeto") or "")[:60]
            L.append(f"- {c.get('data') or '—'} | {c.get('orgao') or '—'} | "
                     f"{_moeda(c.get('valor'))} | {', '.join(c['bandeiras'])} — {obj}")
        L.append("")

    L.append("> Indícios sujeitos a apuração — nunca veredito.")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Orquestração
# ---------------------------------------------------------------------------
def verificar(conn: sqlite3.Connection) -> dict:
    """Detecta novidades e devolve as listas + o Markdown do alerta."""
    contratos = detectar_contratos_novos(conn)
    fornecedores = detectar_fornecedores_novos(conn)
    alerta = gerar_alerta_md(contratos, fornecedores)
    return {"contratos_novos": contratos, "fornecedores_novos": fornecedores, "alerta_md": alerta}


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitoramento incremental do Observatório.")
    parser.add_argument("--coletar", action="store_true", help="rodar PNCP + sanções antes")
    parser.add_argument("--saida", default="data/alerta.md", help="caminho do alerta .md")
    args = parser.parse_args()

    conn = init_db()
    if args.coletar:
        print("Coletando...")
        print(" ", coletar(conn))

    resultado = verificar(conn)
    with open(args.saida, "w", encoding="utf-8") as f:
        f.write(resultado["alerta_md"])
    print(f"{len(resultado['fornecedores_novos'])} fornecedor(es) e "
          f"{len(resultado['contratos_novos'])} contrato(s) novos. Alerta em {args.saida}.")
    conn.close()


if __name__ == "__main__":
    main()
