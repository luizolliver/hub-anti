# Manual de deploy — Observatório de Contratações (Barretos/SP)

Passo a passo para instalar as dependências, **popular o banco** do zero e subir
o painel. Os comandos vêm em duas variantes: **PowerShell (Windows)** e **bash
(Linux/macOS/servidor)**. Rode tudo a partir da **raiz do repositório**.

> O banco fica em `data/observatorio.db` (está no `.gitignore`), então ele
> **não** vem no repositório: precisa ser construído no servidor com os passos
> da seção 3. Tempo total da 1ª carga: ~1 h a 1 h30 (a maior parte é o
> enriquecimento societário; veja as notas de cada passo).

---

## 1. Pré-requisitos

- **Python 3.11+** (testado em 3.13) e **git**.
- Acesso à internet de saída (as coletas batem em PNCP, TCE-SP, BrasilAPI,
  Portal da Transparência e TSE).
- **Opcional (dossiê em PDF):** bibliotecas GTK/Pango do sistema, exigidas pelo
  `weasyprint`. Sem elas, o dossiê em **Markdown e HTML** funciona normalmente;
  só o PDF fica indisponível. Veja
  <https://doc.courtbouillon.org/weasyprint/stable/first_steps.html>.

---

## 2. Instalação

**PowerShell (Windows):**
```powershell
git clone <URL-DO-REPO> hub-anti
cd hub-anti
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**bash (Linux/macOS):**
```bash
git clone <URL-DO-REPO> hub-anti
cd hub-anti
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> Depois de ativar o venv, os comandos abaixo usam apenas `python` (já é o do
> venv). Se preferir não ativar, troque `python` por `.\.venv\Scripts\python.exe`
> (Windows) ou `./.venv/bin/python` (Linux).

Verifique a instalação rodando a suíte de testes (offline, ~5 s):
```bash
pytest -q
```

---

## 3. Popular o banco (ordem importa)

O encadeamento é: **contratos + despesas → tabela `fornecedores` → QSA
(sócios) → cruzamentos (sanções, doações)**. Rode os passos **nesta ordem**.

### 3.1 Criar o schema
```bash
python -m src.db
```

### 3.2 Contratos do PNCP (com fornecedor vencedor)
Traz os contratos recentes (Lei 14.133) e **enriquece o fornecedor** pela API de
detalhe do PNCP. ~2–5 min.
```bash
python -m src.collectors.pncp --paginas 6 --enriquecer
```

### 3.3 Ajustes/Contratos do TCE-SP (Cubo Audesp, 2018→atual)
Raspa os ZIPs de "ajustes" do portal de dados abertos e filtra Barretos. ~3–6 min.
```bash
python -m src.collectors.tce_licitacoes
```

### 3.4 Despesas do TCE-SP (empenho→liquidação→pagamento), 2014→ano atual
Fonte primária do dinheiro pago por CNPJ. São ~156 requisições (12 meses × ~13
anos, ~880 mil linhas). ~8–12 min. **Ajuste o ano final para o ano corrente.**

**PowerShell:**
```powershell
foreach ($ano in 2014..2026) {
  python -m src.collectors.tce_despesas --ano $ano --meses 1-12
}
```

**bash:**
```bash
for ano in $(seq 2014 2026); do
  python -m src.collectors.tce_despesas --ano "$ano" --meses 1-12
done
```

### 3.5 Construir a tabela única de `fornecedores`
Agrega contratos (PNCP+TCE) e despesas por CNPJ. Rápido (~5 s).
```bash
python -m src.normalize.entidades
```

### 3.6 Enriquecimento societário (Receita/QSA via BrasilAPI)
Preenche `empresas` (situação cadastral, natureza, abertura) e `socios` (QSA) —
base das bandeiras de situação, empresa nova, entidade sem fins lucrativos e da
rede de sócios. Processa em ordem de valor e respeita cache; **é o passo mais
lento** (~0,5 s/CNPJ).

- **Completo** (todos os fornecedores; ~40–60 min):
  ```bash
  python -m src.collectors.cnpj --limite 100000
  ```
- **Enxuto** (só os de maior porte — bom para um 1º deploy; ~10 min):
  ```bash
  python -m src.collectors.cnpj --limite 1000
  ```
  > Dá para rodar o "completo" depois: o cache (`--dias-cache`, padrão 30) evita
  > rebuscar quem já foi enriquecido.

### 3.7 Sanções CEIS/CNEP (Portal da Transparência) + cruzamento
Baixa as listas atuais e cruza por CNPJ e por CPF-núcleo+nome. ~1–2 min.
```bash
python -m src.collectors.sancoes
```

### 3.8 Doações de campanha (TSE) — eleições municipais
Lê só o membro de SP do ZIP nacional (range requests) e cruza doador↔sócio /
doador↔fornecedor. ~2–4 min por ano.
```bash
python -m src.collectors.tse --ano 2024
python -m src.collectors.tse --ano 2020
```

### 3.9 Reconstruir `fornecedores` (consolidação final)
Depois dos enriquecimentos, reconstrói para consolidar valores/fontes. ~5 s.
```bash
python -m src.normalize.entidades
```

### Verificação rápida do banco
```bash
python -c "from src.db import init_db; c=init_db(); \
print('fornecedores', c.execute('SELECT COUNT(*) FROM fornecedores').fetchone()[0]); \
print('contratos  ', c.execute('SELECT COUNT(*) FROM contratos').fetchone()[0]); \
print('despesas   ', c.execute('SELECT COUNT(*) FROM despesas').fetchone()[0]); \
print('sancoes    ', c.execute('SELECT COUNT(*) FROM sancoes_encontradas').fetchone()[0]); \
print('doacoes    ', c.execute('SELECT COUNT(*) FROM doacoes_relacionadas').fetchone()[0])"
```
Ordem de grandeza esperada após a carga completa: fornecedores ~7 mil, contratos
~8,8 mil, despesas ~880 mil, sanções centenas, doações dezenas.

---

## 4. Subir o painel

O tema headless já está em `.streamlit/config.toml`.
```bash
streamlit run app/dashboard.py
```
Abre em <http://localhost:8501>.

**Deploy em servidor (porta/endereço públicos):**
```bash
streamlit run app/dashboard.py --server.port 8501 --server.address 0.0.0.0
```
Coloque atrás de um proxy reverso (nginx/Caddy) com HTTPS. Para rodar como
serviço, use `systemd` (Linux) ou o Agendador de Tarefas/NSSM (Windows) apontando
para o binário do venv:
```
./.venv/bin/streamlit run app/dashboard.py --server.port 8501 --server.address 0.0.0.0
```

---

## 5. Atualização incremental (monitor)

Depois da 1ª carga, use o monitor para detectar **novidades** e gerar um alerta
em Markdown (`data/alerta.md`) sem reprocessar tudo:
```bash
python -m src.monitor --coletar     # coleta PNCP+sanções e detecta o que é novo
python -m src.monitor               # só detecta sobre o que já está no banco
```

Para dados frescos periódicos, reexecute os coletores relevantes (a deduplicação
é idempotente — rodar de novo não duplica) e reconstrua `fornecedores`:
```bash
python -m src.collectors.pncp --paginas 6 --enriquecer
python -m src.collectors.tce_licitacoes
python -m src.collectors.sancoes
python -m src.normalize.entidades
```

**Agendar (diário, 7h):**

- **Linux (cron):**
  ```cron
  0 7 * * *  cd /caminho/hub-anti && ./.venv/bin/python -m src.monitor --coletar
  ```
- **Windows (Agendador de Tarefas):** ação "Iniciar programa" →
  `C:\caminho\hub-anti\.venv\Scripts\python.exe` com argumentos
  `-m src.monitor --coletar` e "Iniciar em" `C:\caminho\hub-anti`.

---

## 6. Notas e solução de problemas

- **`ModuleNotFoundError: config`** ao rodar o painel: rode sempre a partir da
  raiz do repositório. O `app/dashboard.py` já insere a raiz no `sys.path`.
- **APIs externas fora do ar:** os coletores têm retry/backoff e são tolerantes
  (uma falha pontual não derruba a carga). Reexecute o passo — a deduplicação
  evita duplicatas.
- **BrasilAPI (QSA) com muitos CNPJs:** o passo 3.6 é longo. Pode ser
  interrompido e retomado; o cache pula quem já foi enriquecido.
- **`data/` não versionado:** é intencional (`.gitignore`). O banco é sempre
  construído no destino pelos passos da seção 3.
- **PDF do dossiê ausente:** normal sem GTK/Pango. Markdown e HTML seguem
  funcionando; instale o `weasyprint` + GTK só se precisar de PDF.
- **Recarga do zero:** apague `data/observatorio.db` e refaça a seção 3.
