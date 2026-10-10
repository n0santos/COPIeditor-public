# ODR-015 — Arquitetura de Release ODK, Split de Módulos e Dissolução do copi-base.ttl

**Status:** Accepted (investigação do repo da ontologia concluída em 2026-06-15)
**Date:** 2026-06-15
**Relação com decisões anteriores:** refina ODR-014 (export do editor); aposenta `copi-base.ttl` como nome de arquivo de fonte.

## Context

Repo da ontologia é ODK-padrão (v1.6): `src/ontology/` com `copi-odk.yaml`, `Makefile`+`copi.Makefile`, `copi-edit.owl` (OFN), `imports/`, `mirror/`. Workflows: `qc.yml` (validação em PR/push via `make test`), `deploy.yml` (`make prepare_release` → 8 artefatos + GitHub Release + SFTP para o servidor UFRGS), `docs.yml` (desabilitado).

Dois artefatos com conteúdo sobreposto e convenções conflitantes existem fora do release pipeline: **`copi-core_4.ttl`** (núcleo qualidade-paper, IRIs *slash*, `iof-av` 202602, perfil bilíngue completo, autossuficiente, com bloco interno `PREVIEW: copi-enriched` marcado para sair) e **`copi-base.ttl` do repo do COPIeditor** (legado de ODR-006/009/010/011, IRIs *hash*, `iof-av` antigo, anotação rasa). Atenção: o `/copi-base.ttl` na raiz do repo da ontologia é coisa **diferente** — é o release artefact gerado pelo ODK.

## Findings confirmados pela investigação

- **F1 — Colisão `-base` ativa.** `release_artefacts: [base,…]` gera `copi-base.owl/ttl` com semântica ODK ("ontologia sem axiomas externos", `--axioms external` removidos; `dce:type IAO_8000001`). Um componente/arquivo de fonte chamado `copi-base` colide com targets do Makefile e IRIs publicadas.
- **F2 — Edição monolítica.** O COPIeditor faz patch direto no `copi-edit.owl` via GitHub API; não há staging por módulo. Não existe `src/ontology/components/`; `components:` ausente do yaml; `OTHER_SRC` vazio.
- **F3 — Reasoner EL no QC.** `reason_test` usa ELK; os 5 checks SPARQL são os padrão ODK (`owldef-self-reference`, `iri-range`, `label-with-iri`, `multiple-replaced_by`, `dc-properties`). Os 10 guards do `verify_owl.sh` **não** estão no QC. ELK ignora `only`/disjunção/inverse — insuficiente para os entailments do COPI.
- **F4 — Versões divergentes + catálogo incompleto.** IOF-Core: 202502 (edit), 202601 (yaml/mirror), 202602 (core alvo). O catálogo só mapeia as IRIs dos módulos `imports/`, não as IRIs upstream que o edit file realmente importa → release builds buscam BFO/IOF na rede. `*_terms.txt` vazios (extração BOT pelo seed).
- **F5 — Publicação.** IRI canônica `https://www.inf.ufrgs.br/ontologies/copi.owl` serve `copi.owl` (= full, imports mesclados). `copi-base.owl` (só axiomas COPI) é servido em `…/copi/copi-base.owl`. Sem w3id/PURL/redirect.

## Decision

1. **IRI = slash.** Namespace canônico `…/copi/`. IRIs *hash* do `copi-base.ttl` reescritos para *slash*.
2. **`iof-av` = 202602** (`…/annotation/`). Resolvido na fonte ao unificar a versão IOF-Core (D6).
3. **`-base` reservado ao ODK.** O módulo core autorado à mão é **`copi-core`**. O release `copi-base.owl` continua sendo o artefato gerado pelo ODK e é o **alvo de import para downstreams** (OntoKG aponta `owl:imports` para `…/copi/copi-base.owl`, não para o full).
4. **Split em componentes ODK** (`src/ontology/components/`):
   - **`copi-core.ttl`** — regime editorial, autorado à mão, justificado por ODR. = `copi-core_4.ttl` menos o bloco PREVIEW. **O COPIeditor não escreve nele.**
   - **`copi-enriched.owl`** — regime de agregação de normas, **escrito pelos PRs do COPIeditor**. ~150 universais folha. Importa `copi-core`.
   - **`copi-vocab.ttl`** (opcional) — vocabulário compartilhado resgatado do `copi-base` (parents de função/processo, participantes ODR-010, qualities, ICE), re-anotado, *slash*. Abaixo do core na cadeia. Criado só se compartilhado por muitos módulos; senão dobrado no enriched.
5. **`copi-edit.owl` deixa de ser monolítico e vira SEED** (header + `owl:imports` dos componentes e import modules). O conteúdo atual do edit file é inventariado e desmembrado: core → `copi-core` (reconciliar com `copi-core_4`); folhas → `copi-enriched`; vocab compartilhado → `copi-vocab`.
6. **Versão IOF-Core unificada em 202602.** Atualizar `mirror_from` no yaml, o mirror local, e o `Import()` do edit file (hoje 202502). Isso alinha `construct/`/`annotation/` com o `copi-core`.
7. **Catálogo offline.** Redirecionar as IRIs upstream de BFO e IOF-Core no `catalog-v001.xml` para os mirrors locais, para release builds sem rede.
8. **Dissolução do `copi-base.ttl` (COPIeditor).** Triagem: (A) 9 categorias de operação = duplicatas supersedidas → deletar (core autoritativo); (B) parents de função/processo, participantes, qualities, ICE → `copi-vocab`/abaixo-do-core; (C) genus/process stubs → `copi-enriched`. Arquivo deletado ao final.
9. **Dois regimes de proveniência**, anotados via `dcterms:source` (→ ODR no editorial; → cláusula de norma no enriched). Ambos batem o mesmo perfil: `@en`+`@pt-br` em `rdfs:label` e `iof-av:naturalLanguageDefinition`, `iof-av:isPrimitive`, FOL onde aplicável.
10. **QC com reasoner correto.** Os guards específicos do COPI (entailment + não-entailment) rodam sob **HermiT**, num target de QC dedicado e **escopado** (componentes COPI + imports mínimos), preservando ELK para os checks EL rápidos do `reason_test`. Migrar os 10 guards do `verify_owl.sh` para `src/sparql/*-violation.sparql` + adicionar a query de completude de perfil de anotação cobrindo todos os componentes.

## Consequences

- **COPIeditor exige mudança** (Fase 2): escrever em `components/copi-enriched.owl`, importar `copi-core`, PRs mirando o componente. Sessão de execução separada.
- **`prepare_release`** passa a rodar com `COMP=true`; `components:` declarado no yaml; Makefile regenerado via `sh run.sh odk.py update` (não editar o Makefile à mão; overrides pontuais em `copi.Makefile`).
- **A migração normaliza IRIs/ns do `copi-base` ANTES** de diferenciar contra o `copi-core_4` (em *hash*, toda classe parece nova).
- **HermiT no full mesclado é pesado** → daí o target escopado para os guards, não sobre a release inteira.
- **O bloco PREVIEW** sai do `copi-core_4` para o `copi-enriched`.
- **Falta inventariar o `copi-edit.owl` atual** (a investigação não dumpou seu conteúdo de classes) — pré-requisito da Fase 1, para saber o que já está lá vs. `copi-core_4` vs. o `copi-base` do editor.

## Migração (duas fases, cada uma com gate verde no QC)

- **Fase 1 — repo da ontologia, sem tocar o COPIeditor.** Inventariar `copi-edit.owl`; declarar componentes no yaml + regenerar; criar `components/{copi-core,copi-enriched,copi-vocab}`; desmembrar o edit file (vira seed); unificar versão (D6) + catálogo offline (D7); triar/dissolver o `copi-base` (D8); migrar guards sob HermiT (D10).
- **Fase 2 — COPIeditor.** Reapontar a escrita para `components/copi-enriched.owl`; serializer importa `copi-core`.

## Relação com ODR-014

ODR-014 (export module-only do editor) permanece válido **mas seu alvo muda**: o editor passa a escrever no componente `copi-enriched`, não no `copi-edit.owl` monolítico. ODR-015 governa como o repo transforma componentes em releases via ODK.

---

## Notas de implementação (Fase 1, 2026-06-18)

### Mecanismo nativo de componente ativado via `make update` (PR #11, COPI)

O `odk.py update` (ODK v1.6→v1.6.1) foi aplicado em COPI PR #11. O Makefile gerado pelo
ODK passa a declarar `OTHER_SRC` nativamente com os três componentes:

```makefile
OTHER_SRC = components/copi-core.ttl components/copi-vocab.ttl components/copi-enriched.owl
```

Os overrides redundantes que antecipavam esse suporte em `copi.Makefile` foram removidos:
- `mirror-iof-core` override (o yaml já aponta para 202602)
- `COMPONENT_FILES` e a sobrescrita de `OTHER_SRC`

O `copi.Makefile` mantém apenas os overrides não cobertos pelo scaffolding gerado:
`$(ONT)-base.owl`, `$(ONT).owl`, `$(ONT).ttl` (IRIs canônicas COPI) e o target `guards`
(HermiT + SPARQL de violação escopados).

---

## Phase 2 — scope and triggers (deferred)

Phase 1 (this ODR) split the ontology into `copi-core`, `copi-enriched`, and `copi-base`,
with `copi-enriched` carried as a hand-authored placeholder. Phase 2 activates COPIeditor
as the generator of `copi-enriched` — moving that module from hand-authored to derived —
and lands the items that depend on it.

### Scope — what Phase 2 generates
The leaf universals that left `copi-core` for `copi-enriched`: leaf functions
(`PumpingFunction`, `CompressionFunction`, `HeatTransferFunction`, `GasAbsorptionFunction`,
`VaporizationFunction`, `TemperatureSensingFunction`) and equipment leaves (`Pump`,
`Compressor`, `GasAbsorber`, `ShellAndTubeHeatExchanger`, `TemperatureSensor`), each with
its function/realization axioms, generated rather than hand-authored.

### Readiness already in place (Phase 1 carry-over)
The serializer emits the correct profile: `iof-av:naturalLanguageDefinition` (not
`obo:IAO_0000115`), IOF-Core pinned to `202602`, and `iof-core:hasSpecifiedOutput` for
process outputs (ODR-010). Generated `copi-enriched` inherits these.

### Items Phase 2 delivers (currently deferred)
- **Enriched provenance (§9, second regime):** `dcterms:source` → norm clause (e.g.,
  ISO 14224 / IEC 81346-2), emitted per class by the serializer.
- **`copi:ControlValve` declaration** (and any other deferred leaves), which **activates the
  dormant guards 02 and 04** (annotated dormant in `docs/dormant-guard-annotation`).
- **Build switch:** `copi-enriched` moves from hand-authored to build-generated (ODK
  component mechanism; today `COMP=false` because components are hand-authored). Validate the
  generated module against the intended content (`robot diff`), then switch the build source.

### Validation gate
Generated `copi-enriched` + full ontology must pass OWL 2 DL, HermiT consistency, and all
guards — including the now-active 02/04.

### Triggers / preconditions
- Leaf set finalized (the functions/equipment above, plus `ControlValve`).
- COPIeditor stays anonymized until the JWS paper; generating `copi-enriched` does not expose
  the tool name (the output is plain OWL), so this does not itself block Phase 2.
