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

## Monitoramento (Etapa 11)

```bash
python -m src.monitor              # detecta novidades no banco atual e gera data/alerta.md
python -m src.monitor --coletar    # roda PNCP + sanções antes de detectar
```

Gera um alerta em Markdown só com o que é **novo** desde a última execução
(contratos sinalizados e fornecedores que entraram/subiram de nível); o estado
fica em `monitor_estado`, então rodar de novo não repete. Agende com `cron`
(Linux), Agendador de Tarefas (Windows) ou GitHub Actions, ex. diário:

```cron
0 7 * * *  cd /caminho/observatorio && .venv/bin/python -m src.monitor --coletar
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
- [x] **Etapa 2B** — Ajustes/Contratos TCE-SP (Cubo Audesp Fase IV, 2018–2024; lado-contrato com CNPJ do fornecedor)

> **Escopo da Etapa 2B:** o arquivo de *Ajustes* é o lado-**contrato** do TCE e
> traz o fornecedor contratado (CNPJ + nome). O coletor **raspa** os ZIPs do
> portal de Dados Abertos (nomes irregulares), filtra Barretos pela coluna
> `Município` e deduplica pelo **Código do Ajuste**. Para ajustes cujo
> instrumento é *Nota de Empenho* (sem nº/valor/assinatura de contrato), o valor
> e a data vêm da própria nota. Mesmo agora, o join PNCP↔TCE de *contratos*
> segue limitado: a search API do PNCP não traz fornecedor e os ajustes não
> trazem o CNPJ do órgão — falta uma chave forte compartilhada.
- [x] **Etapa 3** — Resolução de entidades (normalização CNPJ/CPF/nome, tabela `fornecedores`, reconciliação)

> **Escopo honesto da Etapa 3:** a tabela `fornecedores` é construída sobretudo a
> partir das **despesas do TCE** (que já trazem CNPJ). Não há, hoje, vínculo
> contrato-PNCP↔fornecedor: o lado-TCE de *contratos* só chega na Etapa 2B, e
> despesa ≠ contrato (juntar exigiria casar por empenho). O CNPJ é guardado em
> raiz (8 díg., agrupa matriz+filiais) e completo (14). CPF vem mascarado, mas a
> máscara expõe os **6 dígitos do meio** → pessoa física casa por **(nome +
> dígitos visíveis)** com nível de confiança (`nivel_vinculo_socio`:
> forte/provável/investigar), quase imune a homônimo.
- [x] **Etapa 4** — Enriquecimento societário (CNPJ/QSA via BrasilAPI; `empresas` + `socios`, cache)
- [x] **Etapa 5** — Sanções CEIS/CNEP (cruzamento por CNPJ e por CPF-núcleo+nome; idade da empresa). Apenados do TCE: sub-etapa de raspagem adiada
- [x] **Etapa 6** — Motor de bandeiras vermelhas (`analysis/flags.py`, 1 função pura por regra + agregador)
- [x] **Etapa 7** — Rede societária (`networkx`: sócio em comum + clusters; export `pyvis` HTML)
- [x] **Etapa 8** — Doações de campanha TSE (range no zip nacional; doador↔sócio por CPF-núcleo+nome, doador↔fornecedor por CNPJ)
- [x] **Etapa 9** — Dossiês (Markdown + HTML sempre; PDF opcional via weasyprint/GTK)
- [x] **Etapa 10** — Painel Streamlit (tema hacker; consultas puras testadas; `streamlit run app/dashboard.py`)
- [x] **Etapa 11 (monitoramento)** — atualização incremental + alerta de novidades (`python -m src.monitor --coletar`). Raspagem da Câmara: não feita (opcional)
