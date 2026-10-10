# Issues da auditoria — COPI Editor

Derivadas de `docs/tool_state_report.md` (25/08/2026). Milestone: **JWS submission (2026-10-08)**.

**Labels a criar antes:** `P0-blocks-submission`, `P1-strengthens`, `P2-hygiene`, `integrity`,
`instrumentation`, `ontology`, `investigate`, `paper`, `audit-2026-08`.

**Regra de ordem que precisa sobreviver ao esquecimento:** #1 bloqueia #3. O artefato quebrado
é a evidência do F11 e tem que ser preservado antes de qualquer conserto.

Toda issue leva `audit-2026-08`. Toda issue leva evidência verificável no corpo.

## Mapeamento arquivo → GitHub

Numeração deste arquivo é relativa (#0–#19); não é a numeração real do GitHub — issues
#1–#5 já existiam como PRs antigos no repositório, então a criação real começou em #24.
Resolva qualquer referência cruzada por esta tabela, nunca por dígito — sessões futuras que
re-derivam a numeração por conta própria eventualmente acertam por coincidência e erram sem
perceber.

| Arquivo | GitHub | Título |
|---|---|---|
| #0  | [#43](https://github.com/n0santos/COPIeditor/issues/43) | [TRACKING] Integridade para a submissão JWS |
| #1  | [#24](https://github.com/n0santos/COPIeditor/issues/24) | Congelar a população de análise (closed) |
| #2  | [#25](https://github.com/n0santos/COPIeditor/issues/25) | Composição da população terminal por modelo |
| #3  | [#26](https://github.com/n0santos/COPIeditor/issues/26) | `AllDisjointClasses` removidos do artefato publicado |
| #4  | [#27](https://github.com/n0santos/COPIeditor/issues/27) | `verify_owl.sh` não checa disjunção |
| #5  | [#28](https://github.com/n0santos/COPIeditor/issues/28) | Re-derivar Q1–Q4 |
| #6  | [#29](https://github.com/n0santos/COPIeditor/issues/29) | OOPS! P05/P29 |
| #7  | [#30](https://github.com/n0santos/COPIeditor/issues/30) | Export Zenodo |
| #8  | [#31](https://github.com/n0santos/COPIeditor/issues/31) | `rerun_request` nunca disparou |
| #9  | [#32](https://github.com/n0santos/COPIeditor/issues/32) | `eval_verification_snapshot` travado em 77 |
| #10 | [#33](https://github.com/n0santos/COPIeditor/issues/33) | Escrita não instrumentada |
| #11 | [#34](https://github.com/n0santos/COPIeditor/issues/34) | Harness de ablação |
| #12 | [#35](https://github.com/n0santos/COPIeditor/issues/35) | Registrar w3id/PURL |
| #13 | [#36](https://github.com/n0santos/COPIeditor/issues/36) | Verificar LOV |
| #14 | [#37](https://github.com/n0santos/COPIeditor/issues/37) | ODR-023 |
| #15 | [#38](https://github.com/n0santos/COPIeditor/issues/38) | `divergence_log` não append-only |
| #16 | [#39](https://github.com/n0santos/COPIeditor/issues/39) | Denominador tabela de fontes |
| #17 | [#40](https://github.com/n0santos/COPIeditor/issues/40) | Documentação/artefatos obsoletos |
| #18 | [#41](https://github.com/n0santos/COPIeditor/issues/41) | Diretórios não versionados |
| #19 | [#42](https://github.com/n0santos/COPIeditor/issues/42) | Correções no manuscrito |
| —   | [#44](https://github.com/n0santos/COPIeditor/issues/44) | Enumerate structural guarantees vs published-artifact invariants (F11 input) — aberta 2026-08-26, desmembrada de #27, sem número de arquivo |

Issues abertas fora deste arquivo (achados durante sessões de conserto, ou desmembradas de
uma issue existente) não têm número de arquivo — apenas número real do GitHub.

## Retiering — 2026-08-26

Reclassificação por perda de evidência em curso, não por severidade — ver comentário na
issue de tracking (#43). Tiers vivem como labels/milestone nas issues, não neste arquivo:

- **Tier 1 (bleeding)** — label `tier1-bleeding`: #31, #32, #33, #38
- **Tier 2 (previne recorrência)** — #44
- **Tier 3 (dano estático, necessário ao artigo)** — #29, #35, #36, #37
- **Tier 4 (post-submission)** — milestone `post-submission`: #34, #39, #40, #41
- **Não retieradas nesta passada** (P0-blocks-submission, deixadas como estão): #25, #26, #28,
  #30, #42, #43

---

## #0 — [TRACKING] Integridade para a submissão JWS

`P0-blocks-submission` · `audit-2026-08`

Rastreia todo o trabalho derivado da auditoria de 25/08 contra `main-11.tex`.
Relatório completo: `docs/tool_state_report.md`.

**Bloqueiam a submissão**
- [ ] #1 Congelar a população de análise
- [ ] #2 Composição da população por modelo
- [ ] #3 `AllDisjointClasses` removidos do artefato publicado
- [ ] #4 Invariante de disjunção no `verify_owl.sh`
- [ ] #5 Re-derivar Q1–Q4 sobre a população congelada
- [ ] #6 OOPS! P05 (regressão nova) e P29
- [ ] #7 Export anonimizado de métricas para o Zenodo

**Fortalecem materialmente**
- [ ] #8 `rerun_request` nunca dispara
- [ ] #9 `eval_verification_snapshot` travado em 77
- [ ] #10 Escrita não instrumentada (9 scripts + `/undo`)
- [ ] #11 Harness de ablação e camada de cache/replay
- [ ] #12 Registrar w3id/PURL
- [ ] #13 Verificar status de registro em LOV
- [ ] #14 Fechar ODR-023

**Higiene**
- [ ] #15 `divergence_log` não é append-only
- [ ] #16 Denominador da tabela de escala das fontes
- [ ] #17 Documentação e artefatos obsoletos
- [ ] #18 Diretórios não versionados na árvore de trabalho

**Correções de texto**
- [ ] #19 Correções no manuscrito exigidas pela auditoria

---

## #1 — Congelar a população de análise antes de qualquer correção

`P0-blocks-submission` · `integrity`
**Bloqueia #3, #5, #6, #7. Fazer primeiro, hoje.**

`divergence_log` foi de 993 para 989 porque uma fusão do ODR-022 apagou uma linha de
`enrichment` em julho, cascateando 2 `drop_dangling_disjoint` + 3 `odr022_merge_duplicates`.
Oito scripts de migração não instrumentados entraram depois do corte do artigo e continuam
operando sobre os mesmos dados. **Cada conserto das próximas semanas move números que o artigo
reporta.** É o incidente do F3 acontecendo de novo, ao vivo.

Criar `eval/frozen/2026-08-25/`, somente-leitura, contendo:
- todas as linhas de `enrichment` em status terminal, todas as colunas
- linhas correspondentes de `eval_axiom_snapshot`, `eval_step_field_snapshot`,
  `eval_step_modification_summary`, `eval_genus_usage`, `eval_verification_snapshot`,
  `eval_interaction_event`, `enrichment_history`, `divergence_log`
- o `disjoint_with` JSON por enrichment
- o Turtle combinado atual (pré-publicação) e o `copi-enriched.owl` publicado, byte a byte
- `MANIFEST.md`: contagens por tabela, sha256 por arquivo, git HEAD, SQL exato de cada dump, timestamp

Formato: um `.csv` por tabela mais um `.sqlite`. `README` declarando que todo número do artigo
passa a ser derivado deste diretório, não do banco vivo. Não modificar o banco.

Vira também a base do pacote Zenodo (#7).

---

## #2 — Composição da população terminal por modelo

`P0-blocks-submission` · `investigate`

O artigo alega uma transição, `claude-sonnet-4-20250514` → `claude-sonnet-4-6`. Os dados vivos
mostram três modelos:

| `llm_model` | linhas | primeiro | último |
|---|---|---|---|
| `claude-sonnet-4-20250514` | 260 | 2026-04-08 | 2026-05-04 |
| `claude-sonnet-4-6` | 10 | 2026-06-25 | 2026-06-25 |
| `claude-opus-5` | 17 | 2026-08-08 | 2026-08-08 |

E status: `exported|260`, `proposed|27`. A correspondência 260/260 e 27/(10+17) sugere que a
população analisada é mono-modelo — mas o artigo reportava 261 exportados em 30/06, então a
aritmética admite 1 ou 2 linhas de `sonnet-4-6` dentro da coorte.

```sql
SELECT status, llm_model, COUNT(*), MIN(created_at), MAX(created_at)
FROM enrichment GROUP BY 1,2 ORDER BY 1,2;
```

Entregar: (a) a tabela acima; (b) se algum registro terminal usou modelo diferente de
`claude-sonnet-4-20250514`, listar individualmente com `id`, `cluster_label`, `llm_model`,
`created_at`; (c) quantos registros terminais foram tocados por scripts ODR-020/021/022 depois
de 30/06, rastreado por `enrichment_history`.

Decide se a §6 do artigo declara população mono-modelo ou multi-modelo. Sem isso não dá para
escrever a seção.

---

## #3 — `AllDisjointClasses` removidos do artefato publicado

`P0-blocks-submission` · `integrity`
**Bloqueada por #1** — preservar o artefato quebrado antes de consertar.

`../copi/src/ontology/components/copi-enriched.owl` (1,2 MB, 2026-08-20) contém **zero** axiomas
de disjunção: `grep -ci disjoint` → `0`.

Não é perda de dados a montante:
- `enrichment.disjoint_with`: **295 pares curados**
- Turtle combinado regenerado ao vivo: **294 blocos `AllDisjointClasses`**, 163 classes únicas
  contra 659 sujeitos `owl:Class`, **0 resíduo catálogo-ausente**

Causa raiz: `scripts/regen_enriched_owl.py:212-240`, `remove_protected_subject_triples()`.
A função remove toda tripla com sujeito nó-em-branco que não seja "alcançável" a partir de um
`URIRef` remanescente, como limpeza de órfãos. Axiomas `owl:AllDisjointClasses` têm a forma
`[] rdf:type owl:AllDisjointClasses ; owl:members (...)` — sujeitos nó-em-branco livres que
**nunca são objeto de nenhuma tripla**, logo são classificados como órfãos incondicionalmente
e apagados, independentemente de terem relação com algo removido.

Introduzida em `22ec77d` (**2026-06-25**), antes do corte do artigo. Provavelmente não é drift
novo: a alegação da L625 do `main-11.tex` — que o OWL exportado inclui as declarações
`DisjointWith` aprovadas pelo procedimento — pode já estar errada desde a submissão.

Corrigir e verificar que os 294 blocos sobrevivem ao pipeline de publicação. Guarda em #4.

---

## #4 — `verify_owl.sh` não checa presença de axiomas de disjunção

`P0-blocks-submission` · `integrity`

O portão de release nunca pegou #3 porque nunca procurou. Adicionar invariante de presença e
contagem de disjunção sobre o **artefato publicado**, com ratchet, no mesmo padrão de
`assert_all_classes_anchored()` / `assert_no_information_bearing_artifact()`.

Enquanto isso: enumerar toda garantia estrutural que o artigo reivindica e verificar se cada uma
tem invariante correspondente no artefato publicado — não no estado intermediário. O achado #3
mostra que validador correto + trilha de escrita correta + Turtle intermediário correto **não**
implicam artefato publicado correto.

Essa enumeração alimenta o F11 do artigo.

---

## #5 — Re-derivar Q1–Q4 do Apêndice B sobre a população congelada

`P0-blocks-submission` · `investigate`
**Bloqueada por #1, #2, #3, #6** — os números finais têm que ser os números publicados.

A auditoria não re-rodou Q1–Q4. Consequência: os números de manchete continuam sem verificação.

| Alegação | Onde | Valor no artigo |
|---|---|---|
| Step 1 aceito como está | Tab. 4 / F1 | 98,5% |
| Step 4: aceito / alterado / rejeitado | Tab. 4 | 19,5 / 29,9 / 50,6 |
| `necessary_parts` como % de todas as modificações | F1 | 53,6% |
| Top-3 campos | F1 | 77,8% |
| `axiom_mode` aceito | F1 | 95,4% |
| `genus_bfo_root` content-change | F1a | 16,1% |
| Funções filhas diretas de `DesignedFunction` | F5 | ~72% |
| HermiT: classes / tamanho / tempo | RQ2 | 772 / 1,7 MB / 1,4 s |
| APV violações | RQ2 | 0 |
| `rdfs:label` / `owl:Class` | RQ2 | 2.279 / 1.206 |

Rodar cada um contra `eval/frozen/`, reportar valor no artigo × valor derivado × SQL. HermiT
precisa de execução isolada e fresca — as contagens por `grep` da auditoria não são comparáveis.

---

## #6 — OOPS!: regressão P05 nova e P29 pendente

`P0-blocks-submission` · `ontology`

Execução ao vivo de `scripts/verify_owl.sh` em 25/08: `Critical=2, Important=4, Minor=4`.

- **P05 "wrong inverse relationships" — 6 classes afetadas, contra 0 no corte.** Regressão nova,
  ausente da tabela de severidade do artigo. Triar origem e corrigir.
- **P29 "wrong transitive relationships" — 2 classes, inalterado desde maio.** O artigo atribui a
  um bypass de batch, mas os scripts de migração atuais escrevem `status='proposed'`, nunca
  `status='exported'` — o mecanismo narrado não reproduz contra o código atual. Ou traçar a
  história real das 2 classes, ou corrigir e retirar a explicação causal do artigo.

Não conflitar com a guarda de subsunção não intencional (`73913dd`, `c2ef096`, ratchet fechado
em 13/08) — problema diferente.

Zero Critical na submissão vale muito mais do que explicar dois.

---

## #7 — Export anonimizado de métricas para o pacote Zenodo

`P0-blocks-submission` · `paper`
**Bloqueada por #1**

Não existe script de export. A seção *Data availability* do artigo diz que ele "has not yet been
produced" — ainda verdade, e agora sabidamente barato.

Base: a VIEW `eval_metrics_summary` já separa métricas de texto livre (ids, status, `axiom_mode`,
`llm_model`, contagens de token/custo, booleanos; `cluster_label` é o único quase-identificador
e não é texto licenciado).

Cuidado: `eval_step_field_snapshot` mistura conteúdo bruto — `field_value` guarda rationale e
differentia. Precisa de allowlist por nome de campo antes de exportar.

Reaproveitar a máquina de redação que já existe: `COPYRIGHTED_SOURCES` (`app/jinja_setup.py`) +
`_redact_copyrighted_definitions()` (`enrichment_routes.py`, adicionada em `eb47adf`).

Incluir verificador que falha o build se encontrar trecho literal de ≥8 palavras coincidente com
qualquer definição de norma em `terms.db`. Rodar antes de publicar.

Entregar junto: snapshots datados do OWL, o SQL do Apêndice B como arquivos executáveis,
`analyse.py` que regenera cada número e cada figura, `prompts.py` na íntegra, e um `README`
mapeando cada alegação do artigo ao script e à linha de saída que a produz.

---

## #8 — `rerun_request` nunca disparou; `rerun_resolved` é sempre n.d.

`P1-strengthens` · `instrumentation`

O rodapé da Tabela 4 do artigo culpa `enrichment_history` não consumida. **O diagnóstico está
errado e é verificável por qualquer revisor.**

`_classify_step_modification_type()` (`enrichment/evaluation_metrics.py:101-146,353-357`) nunca
lê `enrichment_history`. Deriva `has_rerun` de `eval_interaction_event.event_type='rerun_request'`.

```sql
SELECT event_type, COUNT(*) FROM eval_interaction_event GROUP BY 1;
-- save|215, open|65, turtle_preview|31 — zero rerun_request, zero rerun_complete
```

A chamada de log existe na rota (`enrichment_routes.py:370`) mas nunca executou.
`enrichment_history` está em 1.062 linhas e é irrelevante para esta métrica — "wire up
enrichment_history" não consertaria nada.

Ou instrumentar a ação de rerun e reportar o número, ou declarar a categoria como não
instrumentada. De qualquer forma, o rodapé do artigo tem que mudar (ver #19).

---

## #9 — `eval_verification_snapshot` travado em 77 linhas desde 07/05

`P1-strengthens` · `instrumentation`

`MIN(created_at) = MAX(created_at) = 2026-05-07T14:27:12` — uma escrita em lote, nunca repetida.
O escritor (`evaluation_metrics.py:244`) só é chamado por caminho manual; nenhuma rota ou script
de migração o invoca. Hoje há 260 classes exportadas, 3,4× a coorte verificada.

Mesma causa raiz da completude de anotação IOF-Core, que o artigo diz estar "in progress" — não
avançou um centímetro, nem antes nem depois do corte.

Não confundir com a cobertura de stubs `skos:definition`, que **foi** fechada, mas antes da
âncora (seis commits em 26/06, 737 stubs de `data/stub-definitions.json`).

Ou avança para as 260, ou o artigo declara a limitação com o número real (77/260) e para de
escrever "in progress".

---

## #10 — Escrita não instrumentada: 9 scripts mais `/undo`

`P1-strengthens` · `instrumentation`

Instrumentados: `/run`, `/rerun/{id}` (`enrichment_routes.py:344,392`), `/queue/{job_id}/run`
(`:1791`), `/{enrichment_id}/update` (`:2229,2251,2278`), `batch_import_results()`
(`enrichment_service.py:4536`).

Não instrumentados — escrevem direto em `enrichment`/`enrichment_history`, nunca chamam
`log_event`/`take_axiom_snapshot`:
`scripts/migrations/odr021_retire_iba.py`, `odr022_canonical_names.py`,
`odr022_enrich_15_components.py`, `odr022_enrich_4_gaps.py`, `odr022_merge_duplicate_classes.py`,
`odr022_normalize_source_definitions.py`, `odr022_repoint_shell.py`,
`scripts/fix_aux_class_signatures.py`, `migration/odr020_migration.py`, mais o não versionado
`scripts/review_duplicates.py`. `/undo` (`:2394`) não loga evento para a própria ação de desfazer.

**Oito dos nove entraram depois da âncora.** A superfície de bypass cresceu, não encolheu — um
verão inteiro de mudanças reais está invisível para qualquer métrica no estilo da Tabela 4.

Não confundir com a "InstrumentationFunction" do ODR-023 (#14), que é questão ontológica.

---

## #11 — Harness de ablação e camada de cache/replay

`P1-strengthens`

Não existe cache de resposta. Os campos `cache_write_tokens`/`cache_read_tokens` do schema são de
billing da Anthropic, não cache de resposta. Sem replay, a ablação não é reproduzível e não vale
o DOI.

Caminho de API já existe (`enrichment_service.py:1309-1533`, mais Batches em ~4403-4536) — o
harness estende, não começa do zero.

Custo por condição:
- **C3 fonte única** — direto, construção do bloco de contexto já parametrizada por cluster
- **C4 Layer-3 desligada** — flag de config; o filtro vive na rota `/update`
  (`enrichment_routes.py:2169-2203`), não no caminho de geração
- **C0 prompt livre** — precisa de **parser novo**: prompt e parsing estão acoplados ao schema
  fixo de cinco passos, com nomes de campo embutidos em `prompts.py` e no parser
- **troca de modelo** — trivial, `DEFAULT_MODEL` é constante única (`enrichment_service.py:82`)

Escopo aprovado: C0, C3, C4. C1 (schema genérico) fora.

Amostra n≈55, estratificada por família de equipamento e `axiom_mode`, seed fixa, persistida.

---

## #12 — Registrar w3id/PURL

`P1-strengthens`

`docs/ontology-decisions/ODR-015-release-architecture-split-copi-base.md:19` — "Sem
w3id/PURL/redirect", inalterado desde 15/06. `curl` ao caminho de release retorna **403**.

É uma das duas lacunas nomeadas que seguram o FOOPS! em 0,868. PR trivial num repo GitHub.
Periódico de comunidade FAIR — o número aparece no artigo.

---

## #13 — Verificar registro em registro de vocabulário (LOV)

`P1-strengthens` · `investigate`

Segunda lacuna nomeada do FOOPS!. **Não determinável a partir deste codebase** — não existe
registro interno em nenhum sentido. Não afirmar resolução nem não-resolução sem checar
externamente.

Nota sobre o score agregado: `3313e19` (HEAD) corrigiu um modo de falha em que uma resposta
HTTP 200 válida com score ~4% e título "unknown" era tratada como score real. **Qualquer
execução FOOPS! anterior a esse commit deve ser tratada com suspeita** — incluindo, possivelmente,
o 0,868 do artigo. Re-executar depois de #12.

---

## #14 — ODR-023: `Instrument ⊑ MeasurementInstrument` inferido ao contrário

`P1-strengthens` · `ontology`

Aberto desde 14/08, decisão pendente. O reasoner infere `Instrument ⊑ MeasurementInstrument`,
invertido em relação à leitura intuitiva e à da ISA-5.1, porque `InstrumentationFunction`
(`COPI_0000029`) carrega restrição `allValuesFrom MeasurementProcess`.

Atinge `COPI_0000024` — **uma das 9 categorias de equipamento do `copi-core` congelado que o
artigo reivindica** — e 27 registros de enrichment.

Também toca o artigo do FOMI. Fechar, ou divulgar como limitação conhecida em ambos. Melhor
divulgar do que um revisor descobrir.

---

## #15 — `divergence_log` não é append-only

`P2-hygiene` · `integrity`

A metodologia do F10 trata a tabela como estável e intocada desde maio. Não é: uma fusão de
classes duplicadas do ODR-022 apagou uma linha de enrichment e cascateou, removendo 4 flags e
1 conceito. 993/293 → **989/292**.

```sql
SELECT divergence_type, COUNT(*) FROM divergence_log GROUP BY 1;
-- T3=378, T5=312, T2=171, T1=118, T4=10 (soma 989)
```

Proporções estáveis (T3 38,2%, T5 31,5%, T2 17,3%, T1 11,9%, T4 1,0%), mas o denominador mudou e
a premissa de imutabilidade é falsa. Ou tornar a tabela realmente imutável, ou documentar a
mutabilidade — e caveat no artigo (#19).

---

## #16 — Denominador da tabela de escala das fontes

`P2-hygiene` · `investigate`

Artigo (L440-460) × `terms.db` ao vivo:

| Fonte | Artigo | `terms.db` |
|---|---|---|
| ISO 15926-4 | ~500 | **17.455** |
| OnePetro | ~5.188 | 5.180 |
| SLB Glossary | ~4.800 | 4.574 |
| POSC Caesar | ~2.000 | 1.192 |
| CFIHOS | ~600 | 862 |
| DEXPI | ~200 | 273 |
| ISA 5.1 | ~80 | 151 |
| ISO 14224 | ~136 | 137 |

Quase certamente denominadores diferentes — escala publicada da norma × linhas ingeridas por
classe (propriedades, sinônimos, arestas de hierarquia). Mas ISO 15926-4 dá 34× de diferença e
está ambíguo o bastante para um revisor ler como discrepância. Confirmar qual denominador a
tabela reporta e anotar.

---

## #17 — Documentação e artefatos obsoletos

`P2-hygiene`

- `CLAUDE.md` diz que a aposentadoria do strip de I/O de processo está "blocked on ODR-021";
  resolvido desde 08/08. Hoje: 0 quarentenadas, 501 restrições admissíveis, 0 classes
  insatisfazíveis.
- `enrichment/output/copi-merged.ttl` — 358 KB, última escrita 01/07, anterior a todo o
  ODR-020/021/022. Regenerar ou remover.

---

## #18 — Diretórios não versionados na árvore de trabalho

`P2-hygiene`

- `validation/` — passe de validação profunda de 77 termos, conteúdo datado de 03/05 mas mtime de
  15/08 por cópia em lote. **Citar por data de conteúdo, nunca por `ls -la`.**
- `submission/` — corpus de verificação de **outro artigo** ("Five-type typology of cross-standard
  conceptual divergences"). **Não conflitar** o corpus T1–T5 de 157 itens com nada do `main-11.tex`.

Versionar, mover ou documentar. Risco real de conflação numa auditoria futura ou num pacote de
reprodução.

---

## #19 — Correções no manuscrito exigidas pela auditoria

`P0-blocks-submission` · `paper`

Checklist. O `main-11.tex` não vive neste repo — esta issue existe para manter visível a
dependência conserto-de-código → número → correção de texto.

- [ ] L625: alegação de que o OWL exportado inclui declarações `DisjointWith` — **falsa**, corrigir após #3
- [ ] Escrever F11 (segunda instância do implementation–enforcement gap) — depende de #3, #4
- [ ] Passada de precisão de referente: declarar, para cada número quantitativo, se descreve o DB, o Turtle intermediário ou o OWL publicado
- [ ] Rodapé de `rerun_resolved` na Tab. 4 — diagnóstico errado, ver #8
- [ ] Taxonomia de status: o artigo descreve 4 incluindo `validated`; hoje só `exported`/`proposed`. A definição de população não parseia mais
- [ ] Modelo: corrigir conforme #2
- [ ] Declaração de uso de IA (L1055): "a Claude Sonnet model" não descreve mais a produção atual
- [ ] Contagens: 272→287 registros, 271→287 conceitos, 261→260 terminais, 11→27 na fila, razão 96,3%→90,6%
- [ ] Genus: Assembly 38→45, MaterialArtifact 23→37, Instrument 21→23, Valve 22→21
- [ ] F10: 993/293 → 989/292, mais caveat de mutabilidade (#15)
- [ ] Tabela OOPS!: perfil de severidade não é idêntico a maio — P05 é novo (#6)
- [ ] Completude IOF-Core: parar de dizer "in progress" (#9)
- [ ] Divulgar ODR-023 como limitação (#14)
- [ ] Denominador da tabela de fontes (#16)
- [ ] Reescrever *Data availability* com o DOI (#7)
- [ ] Comparação de genus na disjunção mudou em 03/08 (`45b440a`, `597d885`): passou de `step2_genus` congelado para a coluna curada `genus`, com comparação insensível a caixa e pontuação. Qualquer figura derivada de execução anterior a 03/08 usou a comparação antiga
- [ ] "Prompt template held constant since 05-03" é enganoso se lido amplamente: `b45ef92` (28/06) reescreveu a regra de evidência do Step 4 exigindo `source_quote` literal, e adicionou vocabulário controlado de `transformation_kind` ao Step 5. O Apêndice A está correto para o arquivo atual; a moldura é que precisa de ajuste

---

## Prompt para criar as issues

````
Create GitHub issues from docs/audit-issues.md in this repo, using `gh`.

First: DRY RUN. Print exactly what you would create — title, labels, milestone, and
the first three lines of each body — and stop for my confirmation. Do not create
anything yet.

Setup (after I confirm):
- create the milestone "JWS submission (2026-10-08)" if absent
- create any missing labels: P0-blocks-submission, P1-strengthens, P2-hygiene,
  integrity, instrumentation, ontology, investigate, paper, audit-2026-08
- create issues in file order so that the numbers referenced in bodies resolve; if
  GitHub assigns different numbers than the file's #N placeholders, rewrite the
  cross-references in the created bodies to the real numbers afterwards
- assign every issue the milestone and the audit-2026-08 label plus its own labels
- issue #1 in the file is the tracking issue: create it LAST, once real numbers are
  known, with its checklist pointing at them

Preserve every code path, line number, commit hash, and SQL block verbatim from the
file — that evidence is the point.

Verify after: print `gh issue list --milestone "JWS submission (2026-10-08)"` and
confirm the tracking issue's checklist links resolve.
````
