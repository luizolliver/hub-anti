# Bandeiras (indícios) do Observatório

Cada **bandeira** é um indício vermelho, rastreável até o dado oficial. O
**nível de atenção** de um fornecedor é a **soma dos pesos** das bandeiras que
ele dispara — nunca um score opaco. O usuário sempre vê *quais* bandeiras
compõem o total.

> ⚠️ Indício não é prova. Casamentos por nome/CPF parcial podem conter
> homônimos; grupos nacionais (matriz+filiais) podem disparar bandeiras de
> rede sem irregularidade. Toda bandeira merece **apuração humana**.

As regras puras estão em [`src/analysis/flags.py`](src/analysis/flags.py); os
pesos no dicionário `PESOS`. A avaliação de fornecedor é centralizada em
`avaliar_fornecedor` (fonte única usada pelo ranking **e** pelo dossiê).

Contagens abaixo referem-se à base atual (Barretos, contratos 2016–2024 +
despesas TCE 2019 + QSA/sanções/doações cruzadas).

---

## Bandeiras de fornecedor

### `SITUACAO_CADASTRAL` — peso 4
- **O quê:** empresa não-ATIVA (baixada/inapta/suspensa) ou com situação especial.
- **Fonte:** Receita Federal (situação cadastral, via BrasilAPI).
- **Lógica:** `situacao_cadastral != 'ATIVA'` ou `situacao_especial` preenchida.
- **Exemplo real:** JULIANA CLEIA TRINDADE GOMES (24640390000122) — **BAIXADA**.
- **Ocorrências:** ~299.

### `FORNECEDOR_SANCIONADO` — peso 5
- **O quê:** o fornecedor ou um sócio consta em lista de sanção.
- **Fonte:** CEIS/CNEP (Portal da Transparência), cruzado por CNPJ ou CPF-núcleo+nome.
- **Lógica:** existe registro em `sancoes_encontradas` para o CNPJ.
- **Exemplo real:** FLORIPARK EMPREENDIMENTOS E SERVIÇOS (82889304000116) — CEIS.
- **Ocorrências:** ~7.

### `CONCENTRACAO` — peso 2
- **O quê:** o fornecedor concentra fatia do gasto **total** pago do município.
- **Fonte:** TCE-SP (despesas pagas) + agregação interna.
- **Lógica:** `valor_pago / total_pago >= 50%`.
- **Exemplo real:** FUNDAÇÃO PIO XII (49150352000112) — 59% do total.
- **Ocorrências:** ~1.

---

## Bandeiras adicionais (Parte 2)

### `EMPRESA_NOVA_NO_CONTRATO` — peso 3
- **O quê:** empresa constituída há **menos de 1 ano** na data do seu primeiro
  contrato com o município.
- **Fonte:** Receita Federal (abertura) × PNCP/TCE (data do 1º contrato).
- **Lógica:** `(data_primeiro_contrato − data_abertura) < 365 dias` (limiar em
  `config.LIMIAR_EMPRESA_NOVA_CONTRATO_DIAS`).
- **Exemplo real:** BOMBEAGUA COM. MAN. BOMBA DE ÁGUA EIRELI (29657583000100).
- **Ocorrências:** ~143.

### `DISPENSA_ACIMA_LIMITE` — peso 3
- **O quê:** **dispensa em razão do valor** com valor **acima do teto legal
  vigente na data do contrato**, exigindo justificativa formal.
- **Fonte:** PNCP/TCE (modalidade + valor + data + objeto).
- **Lógica:** é dispensa por valor (exclui **inexigibilidade** e **dispensa
  emergencial/calamidade**, que não têm teto de valor) **e** `valor > teto`,
  onde o **teto é o vigente no ano do contrato** (`config.LIMITES_DISPENSA`,
  Lei 8.666 → Lei 14.133, com os decretos de atualização). Obra vs. bens/
  serviços é decidido por heurística no objeto. A evidência traz o valor, o
  teto e a data de vigência do teto.
- **Por que por ano:** os contratos vão de 2014 a 2026; um teto fixo geraria
  falso positivo em contrato recente (perto do teto novo) e falso negativo em
  contrato antigo (teto da época era muito menor).
- **Exemplo real:** PORTO SEGURO CIA DE SEGUROS GERAIS (61198164000160).
- **Ocorrências:** ~76.

### `ENTIDADE_SEM_FINS_LUCRATIVOS_SEM_LICITACAO` — peso 4
- **O quê:** entidade sem fins lucrativos (associação/fundação/OSCIP) contratada
  **sem processo licitatório** — padrão comum em repasses via convênio.
- **Fonte:** Receita (natureza jurídica) × PNCP/TCE (modalidade).
- **Lógica:** `natureza_juridica` é do tipo sem fins lucrativos **e** há ao menos
  um contrato por contratação direta.
- **Exemplo real:** CENTRO DE INTEGRAÇÃO EMPRESA-ESCOLA (61600839000155).
- **Ocorrências:** ~14. *Alta relevância para o histórico de Barretos.*

### `CONCENTRACAO_POR_SECRETARIA` — peso 2
- **O quê:** o fornecedor concentra **> 40%** dos contratos de um único órgão num
  mesmo ano — possível direcionamento/dependência.
- **Fonte:** TCE-SP (contratos por órgão/ano) + agregação interna.
- **Lógica:** para algum `(órgão, ano)`, `valor_do_fornecedor / total_do_órgão_ano
  >= 40%`, exigindo ao menos 3 contratos no grupo (evita ruído). A descrição
  nomeia o órgão e o ano.
- **Exemplo real:** GOVERNANÇA BRASIL S/A (00165960000101) — 47% da Câmara num ano.
- **Ocorrências:** ~15.

### `MULTIPLOS_CONTRATOS_OBJETO_SIMILAR` — peso 4
- **O quê:** 3+ contratos com o mesmo órgão e **objeto similar** numa janela de
  90 dias — indício clássico de **fracionamento** para evitar licitação.
- **Fonte:** PNCP/TCE.
- **Lógica:** agrupa por `(órgão, primeiros 40 chars do objeto)`; dispara se há
  janela de `<= 90 dias` com `>= 3` contratos. Parâmetros em
  `config.FRACIONAMENTO_*`.
- **Exemplo real:** D PAPIROS INFORMÁTICA BTOS (03821366000110).
- **Ocorrências:** ~203.

### `SOCIO_MULTIPLAS_EMPRESAS_FORNECEDORAS` — peso 3
- **O quê:** um mesmo sócio aparece em **3+ empresas** que contratam com o
  município — possível grupo econômico atuando como concorrentes.
- **Fonte:** Receita/QSA (sócios) + tabela `fornecedores`.
- **Lógica:** o sócio é casado por `(nome normalizado + 6 dígitos visíveis do
  CPF)`, a mesma noção de "mesma pessoa" da rede (Etapa 7); conta-se quantas
  empresas fornecedoras compartilham o sócio (incl. a própria); dispara em
  `>= 3` (`config.SOCIO_MIN_EMPRESAS_FORNECEDORAS`).
- **Exemplo real:** o cluster de construção (Shalom/Prisma/Talisma + consórcios)
  via Emael Paixão Flavio e Guilherme Polizelli.
- **Ocorrências:** ~50. *Atenção a falsos positivos por matriz+filiais de
  grupos nacionais (ex.: Telefônica).*

---

## Bandeiras de nível de contrato (motor `avaliar`)

Disparam sobre um contrato isolado + contexto (não compõem o nível de
fornecedor agregado, mas alimentam o monitor e análises por contrato):
`DISPENSA_INEXIGIBILIDADE` (2), `EMPRESA_NOVA` (3), `PARTICIPANTE_UNICO` (3),
`ADITIVO_ELEVADO` (3), `SOBREPRECO` (4), `FIM_DE_EXERCICIO` (1). As três
últimas dependem de dados ainda não coletados (participantes, aditivos, preço
unitário por item) e já existem como funções puras testadas.

---

_Para recalcular o nível de todos os fornecedores após mexer numa regra/peso,
basta reabrir o painel (ranking e perfil chamam `avaliar_fornecedor` ao vivo) —
não há score materializado a regenerar._
