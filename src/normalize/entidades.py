"""
Resolução de entidades — Etapa 3 (o "cérebro silencioso").

Sem chaves boas, nenhum cruzamento das etapas seguintes funciona. Aqui ficam:
  - normalização e validação de CNPJ e CPF (com dígitos verificadores);
  - normalização de nomes (maiúsculas, sem acento) para casamento aproximado;
  - reconciliação de um mesmo contrato vindo de fontes diferentes (PNCP/TCE);
  - construção da tabela `fornecedores` única, por CNPJ.

Tudo aqui é função pura e testável offline, exceto `construir_fornecedores`,
que lê/escreve no banco.
"""

from __future__ import annotations

import re
import sqlite3
import unicodedata

# ---------------------------------------------------------------------------
# Documentos: dígitos, validação e normalização
# ---------------------------------------------------------------------------
def so_digitos(valor: str | None) -> str:
    """Mantém apenas os dígitos. String vazia se None."""
    if not valor:
        return ""
    return re.sub(r"\D", "", str(valor))


def _dv(base: str, pesos: list[int]) -> str:
    """Calcula um dígito verificador (módulo 11) para CNPJ/CPF."""
    soma = sum(int(d) * p for d, p in zip(base, pesos))
    resto = soma % 11
    return "0" if resto < 2 else str(11 - resto)


def cnpj_valido(cnpj: str | None) -> bool:
    """True se o CNPJ tem 14 dígitos e os dois dígitos verificadores conferem."""
    c = so_digitos(cnpj)
    if len(c) != 14 or c == c[0] * 14:
        return False
    d1 = _dv(c[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = _dv(c[:12] + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return c[12] == d1 and c[13] == d2


def cpf_valido(cpf: str | None) -> bool:
    """True se o CPF tem 11 dígitos e os dígitos verificadores conferem."""
    c = so_digitos(cpf)
    if len(c) != 11 or c == c[0] * 11:
        return False
    d1 = _dv(c[:9], list(range(10, 1, -1)))
    d2 = _dv(c[:10], list(range(11, 1, -1)))
    return c[9] == d1 and c[10] == d2


def normalizar_cnpj(cnpj: str | None) -> str | None:
    """Devolve o CNPJ com 14 dígitos se for válido; senão None."""
    c = so_digitos(cnpj).zfill(14) if cnpj else ""
    return c if cnpj_valido(c) else None


def normalizar_cpf(cpf: str | None) -> str | None:
    """Devolve o CPF com 11 dígitos se for válido; senão None."""
    c = so_digitos(cpf).zfill(11) if cpf else ""
    return c if cpf_valido(c) else None


# ---------------------------------------------------------------------------
# Nomes: chave para casamento aproximado
# ---------------------------------------------------------------------------
def normalizar_nome(nome: str | None) -> str:
    """
    Gera uma chave de comparação: maiúsculas, sem acentos, sem pontuação,
    espaços colapsados. Ex.: 'Telefônica Brasil S.A.' -> 'TELEFONICA BRASIL S A'.

    Serve para casar nomes equivalentes (doador x sócio, p.ex.). Não é prova:
    homônimos existem (ver guardrails do blueprint).
    """
    if not nome:
        return ""
    # Remove acentos.
    sem_acento = "".join(
        c for c in unicodedata.normalize("NFKD", str(nome)) if not unicodedata.combining(c)
    )
    # Mantém só letras/números/espaço; o resto vira espaço.
    limpo = re.sub(r"[^A-Za-z0-9 ]+", " ", sem_acento)
    # Colapsa espaços e maiúsculas.
    return re.sub(r"\s+", " ", limpo).strip().upper()


# ---------------------------------------------------------------------------
# Reconciliação de contratos entre fontes (PNCP x TCE-SP)
# ---------------------------------------------------------------------------
def chave_reconciliacao(contrato) -> tuple:
    """
    Chave heurística para decidir que dois contratos de fontes diferentes são
    o mesmo: mesmo órgão, ano, fornecedor e valor (arredondado).

    Aceita um objeto Contrato (pydantic) ou um dict equivalente.
    """
    g = (lambda k: getattr(contrato, k, None)) if not isinstance(contrato, dict) else contrato.get
    valor = g("valor")
    return (
        so_digitos(g("orgao_cnpj")) or None,
        (g("ano") or None),
        so_digitos(g("fornecedor_cnpj")) or None,
        round(float(valor), 2) if valor is not None else None,
    )


def reconciliar_contratos(contratos: list) -> list:
    """
    Mescla contratos que aparecem em mais de uma fonte num registro canônico.

    Para cada grupo (mesma `chave_reconciliacao`), mantém o primeiro contrato,
    preenche campos vazios com o que a outra fonte tiver e registra todas as
    fontes em `raw['fontes']` e os ids de origem em `raw['ids_origem']`.
    Contratos sem chave útil (tudo None) nunca são mesclados entre si.
    """
    grupos: dict[tuple, list] = {}
    soltos: list = []
    for c in contratos:
        chave = chave_reconciliacao(c)
        if all(parte is None for parte in chave):
            soltos.append(c)  # sem identidade suficiente: não mescla
            continue
        grupos.setdefault(chave, []).append(c)

    canonicos: list = []
    for membros in grupos.values():
        canonico = membros[0]
        fontes = []
        ids = []
        for m in membros:
            if m.fonte and m.fonte not in fontes:
                fontes.append(m.fonte)
            if m.id:
                ids.append(m.id)
            # Preenche campos faltantes do canônico com os dos demais.
            for campo in (
                "fornecedor_cnpj", "fornecedor_nome", "objeto",
                "modalidade", "orgao", "orgao_cnpj", "data", "valor",
            ):
                if getattr(canonico, campo, None) in (None, "") and getattr(m, campo, None):
                    setattr(canonico, campo, getattr(m, campo))
        canonico.raw = {**(canonico.raw or {}), "fontes": fontes, "ids_origem": ids}
        canonicos.append(canonico)

    return canonicos + soltos


# ---------------------------------------------------------------------------
# Tabela de fornecedores únicos
# ---------------------------------------------------------------------------
def _escolher_nome(nomes: list[str]) -> str | None:
    """Escolhe o nome canônico: o mais frequente; empate desempata pelo maior."""
    nomes = [n for n in nomes if n]
    if not nomes:
        return None
    contagem: dict[str, int] = {}
    for n in nomes:
        contagem[n] = contagem.get(n, 0) + 1
    return max(nomes, key=lambda n: (contagem[n], len(n)))


def construir_fornecedores(conn: sqlite3.Connection) -> int:
    """
    Varre `contratos` (PNCP) e `despesas` (TCE) e monta a tabela `fornecedores`
    única por CNPJ válido. Retorna o número de fornecedores distintos.

    Para cada CNPJ: nome canônico, nº de contratos/despesas, valor de contratos,
    valor pago (despesas com evento 'Valor Pago') e as fontes.
    """
    agreg: dict[str, dict] = {}

    def _slot(cnpj: str) -> dict:
        return agreg.setdefault(
            cnpj,
            {
                "nomes": [], "n_contratos": 0, "n_despesas": 0,
                "valor_contratos": 0.0, "valor_pago": 0.0, "fontes": set(),
            },
        )

    # Fornecedores vindos do PNCP (contratos).
    for row in conn.execute(
        "SELECT fornecedor_cnpj, fornecedor_nome, valor FROM contratos "
        "WHERE fornecedor_cnpj IS NOT NULL"
    ):
        cnpj = normalizar_cnpj(row["fornecedor_cnpj"])
        if not cnpj:
            continue
        s = _slot(cnpj)
        s["nomes"].append(row["fornecedor_nome"])
        s["n_contratos"] += 1
        s["valor_contratos"] += row["valor"] or 0
        s["fontes"].add("PNCP")

    # Fornecedores vindos do TCE (despesas com CNPJ).
    for row in conn.execute(
        "SELECT fornecedor_documento, fornecedor_nome, evento, valor FROM despesas "
        "WHERE fornecedor_tipo='CNPJ' AND fornecedor_documento IS NOT NULL"
    ):
        cnpj = normalizar_cnpj(row["fornecedor_documento"])
        if not cnpj:
            continue
        s = _slot(cnpj)
        s["nomes"].append(row["fornecedor_nome"])
        s["n_despesas"] += 1
        if row["evento"] == "Valor Pago":
            s["valor_pago"] += row["valor"] or 0
        s["fontes"].add("TCE-SP")

    conn.executemany(
        """
        INSERT INTO fornecedores
            (cnpj, nome, nome_chave, n_contratos, n_despesas,
             valor_contratos, valor_pago, fontes)
        VALUES (:cnpj, :nome, :nome_chave, :n_contratos, :n_despesas,
                :valor_contratos, :valor_pago, :fontes)
        ON CONFLICT(cnpj) DO UPDATE SET
            nome=excluded.nome, nome_chave=excluded.nome_chave,
            n_contratos=excluded.n_contratos, n_despesas=excluded.n_despesas,
            valor_contratos=excluded.valor_contratos, valor_pago=excluded.valor_pago,
            fontes=excluded.fontes
        """,
        [
            {
                "cnpj": cnpj,
                "nome": (nome := _escolher_nome(s["nomes"])),
                "nome_chave": normalizar_nome(nome),
                "n_contratos": s["n_contratos"],
                "n_despesas": s["n_despesas"],
                "valor_contratos": round(s["valor_contratos"], 2),
                "valor_pago": round(s["valor_pago"], 2),
                "fontes": ",".join(sorted(s["fontes"])),
            }
            for cnpj, s in agreg.items()
        ],
    )
    conn.commit()
    return len(agreg)


def main() -> None:
    """Reconstrói a tabela `fornecedores` a partir do banco e mostra um resumo."""
    from src.db import init_db

    conn = init_db()
    n = construir_fornecedores(conn)
    print(f"{n} fornecedores únicos (por CNPJ válido).")
    print("\nTop 8 por valor pago (TCE):")
    for r in conn.execute(
        "SELECT cnpj, nome, valor_pago, n_despesas, fontes FROM fornecedores "
        "ORDER BY valor_pago DESC LIMIT 8"
    ):
        print(f"  {r['cnpj']} | R$ {r['valor_pago']:>14,.2f} | {r['fontes']:11} | {(r['nome'] or '')[:34]}")
    conn.close()


if __name__ == "__main__":
    main()
