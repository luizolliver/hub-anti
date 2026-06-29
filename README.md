# Observatório de Contratações Públicas — Barretos/SP

Coleta contratos e licitações de Barretos/SP, descobre as empresas e seus donos,
cruza com listas de punições e doações de campanha e aponta **indícios** (bandeiras
vermelhas explicáveis) para apuração jornalística ou representação ao MP/TCE-SP.

> **Não é um juiz.** Não existe "score de corrupção". Toda saída é um indício
> rastreável até o dado oficial, com fonte e data. Veja os guardrails no blueprint.

## Stack

Python 3.11+ · SQLite · httpx · pydantic · pytest · networkx/pyvis · Streamlit · weasyprint

## Setup

```bash
python -m venv .venv
# Windows (PowerShell):
.venv\Scripts\Activate.ps1
# Linux/Mac:
# source .venv/bin/activate

pip install -r requirements.txt
```

> No Windows, `weasyprint` (Etapa 9) exige bibliotecas GTK/Pango do sistema.
> Instale-o só ao chegar nessa etapa.

## Uso (Etapa 0)

```bash
python -m src.db     # cria o banco SQLite em data/observatorio.db
pytest               # roda a suíte de testes
```

## Estrutura

```
config.py            # constantes: IBGE, código TCE, CNPJs, limiares
src/db.py            # conexão + criação do schema SQLite
src/collectors/      # 1 coletor por fonte (busca e parse separados)
src/normalize/       # normalização de CNPJ/CPF/nomes
src/analysis/        # bandeiras vermelhas + grafo societário
src/reports/         # geração de dossiês
app/dashboard.py     # painel Streamlit
tests/               # testes (offline, sobre fixtures salvas)
```

## Roadmap

O desenvolvimento segue o `blueprint-observatorio-barretos.md`, etapa por etapa
(0 a 11). Cada etapa só "fecha" quando os testes passam.

- [x] **Etapa 0** — Fundação (estrutura, config, banco, pytest)
- [x] **Etapa 1** — Coletor PNCP (search API; enriquecimento de fornecedor via consulta API)

> **Nota de arquitetura — fornecedor:** a fonte **primária** do CNPJ do fornecedor é o
> **TCE-SP** (Etapa 2). O enriquecimento via PNCP (`enriquecer_fornecedor`) é apenas
> bônus para quando a consulta API voltar — não é o caminho principal. Contratos do
> PNCP podem ficar com fornecedor nulo até o cruzamento com o TCE.

- [x] **Etapa 2A** — Despesas TCE-SP (API REST 2014–2019; fonte primária do fornecedor)
- [ ] Etapa 2B — Licitações/Contratos TCE-SP (cubo Fase IV) + CSV em massa
- [x] **Etapa 3** — Resolução de entidades (normalização CNPJ/CPF/nome, tabela `fornecedores`, reconciliação)

> **Escopo honesto da Etapa 3:** a tabela `fornecedores` é construída sobretudo a
> partir das **despesas do TCE** (que já trazem CNPJ). Não há, hoje, vínculo
> contrato-PNCP↔fornecedor: o lado-TCE de *contratos* só chega na Etapa 2B, e
> despesa ≠ contrato (juntar exigiria casar por empenho). O CNPJ é guardado em
> raiz (8 díg., agrupa matriz+filiais) e completo (14). CPF do TCE vem mascarado
> → pessoa física resolve por **nome (fuzzy)**, pista fraca, nunca chave.
- [ ] Etapa 4 — Enriquecimento societário (CNPJ/QSA)
- [ ] Etapa 5 — Sanções (CEIS/CNEP + apenados TCE)
- [ ] Etapa 6 — Motor de bandeiras vermelhas
- [ ] Etapa 7 — Rede societária
- [ ] Etapa 8 — Doações de campanha (TSE)
- [ ] Etapa 9 — Dossiês / relatórios
- [ ] Etapa 10 — Painel Streamlit
- [ ] Etapa 11 — Legislativo + monitoramento contínuo
