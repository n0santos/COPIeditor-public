/**
 * COPPP Editor — lightweight i18n
 * English is the default (no translation applied).
 * pt-BR translations are applied by swapping data-i18n element text.
 *
 * Usage in templates:  data-i18n="key"
 * Usage in JS:         _t('key') || 'English fallback'
 */

const TRANSLATIONS = {
  'pt': {
    // ── Navigation ───────────────────────────────────────────────────
    'nav.ontology':       'Ontologia',
    'nav.requirements':   'Requisitos',
    'nav.terms':          'Termos',
    'nav.workbench':      'Bancada',
    'nav.enrichment':     'Enriquecimento',
    'nav.relations':      'Relações',
    'nav.quality':        'Qualidade',
    'nav.verify':         'Verificar',
    'nav.validate':       'Validar',
    'nav.qa':             'P&R',
    'nav.reference':      'Referência',
    'nav.docs':           'Documentação',
    'nav.api':            'API',
    'nav.imported_onto':  'Ontologias',
    'nav.search_ph':      'Buscar termos…',
    'nav.search_btn':     'Buscar',
    'nav.lang_toggle':    'EN',

    // ── Dashboard ────────────────────────────────────────────────────
    'dash.hero_title':    'Bancada de Enriquecimento RDL',
    'dash.hero_sub':      'Axiomatização assistida por IA usando o método BFO/IOF-Core de 5 etapas',
    'dash.step1':         '① Função Identitária',
    'dash.step2':         '② Definição do Gênero',
    'dash.step3':         '③ Diferença Específica',
    'dash.step4':         '④ Partes Necessárias',
    'dash.step5':         '⑤ Assinatura de Participação em Processo',
    'dash.dl_ontology':   '⬇ Baixar Ontologia',
    'dash.backup_db':     '💾 Backup BD',
    'dash.batch_queue':   '⚙ Fila em Lote',
    'dash.proposals':     'Propostas de Enriquecimento',
    'dash.total':         'total',
    'dash.clusters':      'Clusters Disponíveis',
    'dash.pill_inscope':  'No escopo',
    'dash.pill_oos':      'Fora do escopo',
    'dash.pill_enriched': 'Enriquecido',
    'dash.pill_unenr':    'Não enriquecido',
    'dash.loading':       'Carregando clusters…',
    'dash.show_more':     'Mostrar mais',
    'dash.showing':       'Mostrando',
    'dash.of':            'de',
    'dash.clusters_word': 'clusters',
    'dash.total_word':    'total',
    'dash.sources':       'fonte',
    'dash.sources_pl':    'fontes',
    'dash.search_ph':     'Buscar clusters…',
    'dash.inscope_btn':   '↩ no escopo',
    'dash.oos_btn':       '✕ fora do escopo',
    'dash.run_enr':       'Executar Enriquecimento',
    'dash.rerun_enr':     'Re-executar Enriquecimento',
    'dash.cancel':        'Cancelar',
    'dash.selected':      'selecionado(s)',
    'dash.clear':         'Limpar',
    'dash.add_queue':     '⚙ Adicionar à Fila',
    'dash.enrich_now':    '▶ Enriquecer agora',
    'dash.modal_sources': 'fonte(s)',
    'dash.modal_desc':    'Isso enviará as definições de',
    'dash.modal_desc2':   'para o Claude, que aplicará o método de 5 etapas e proporá axiomas.',

    // ── Enrichment detail ────────────────────────────────────────────
    'det.back':           '← Dashboard',
    'det.reviewer_ph':    'Nome do revisor',
    'det.save':           'Salvar Alterações',
    'det.rerun':          '↺ Re-executar com notas',
    'det.step1':          'Função Identitária',
    'det.step2':          'Gênero Próximo',
    'det.step3':          'Diferença Específica',
    'det.step4':          'Partes Necessárias',
    'det.step5':          'Assinatura de Participação em Processo ⟨E, S, T⟩',
    'det.done':           '✓ feito',
    'det.class_basis':    'Base de Classificação',
    'det.iof_root':       'Raiz IOF-Core',
    'det.iof_assembly':   '⊑ bfo:Object — unidade desmontável (bomba, compressor, trocador)',
    'det.iof_material_artifact': '⊑ bfo:Object — artefato monolítico (válvula, tubo, sensor)',
    'det.iof_engineered_system': '⊑ bfo:ObjectAggregate — disjunto de Assembly/MaterialArtifact',
    'det.fn_class':       'Classe da Função',
    'det.fn_parent':      'Pai',
    'det.proc_class':     'Classe do Processo',
    'det.proc_parent':    'Pai do Processo',
    'det.llm_rationale':  'Justificativa do LLM:',
    'det.genus_label':    'Gênero (genus proximum)',
    'det.genus_hint':     'Superclasse mais específica — pode ser uma classe de domínio como "Válvula" ou uma raiz IOF-Core.',
    'det.bfo_root':       'Raiz BFO',
    'det.axiom_mode':     'Modo do Axioma',
    'det.diff_expr':      'Expressão da diferença',
    'det.diff_nl':        'Diferença (linguagem natural)',
    'det.inherited':      'Herdado do gênero (não repetir no axioma)',
    'det.dist_from':      'Distingue de irmãos',
    'det.parts_add':      '+ Adicionar Parte',
    'det.part_name_ph':   'Nome da parte',
    'det.part_parent_ph': 'Classe pai',
    'det.inputs':         'Entradas (E)',
    'det.outputs':        'Saídas (S)',
    'det.transform':      'Transformação (T)',
    'det.axiom_type':     'Tipo de Axioma',
    'det.necessary':      'Apenas Necessário (⊑ primitivo)',
    'det.necsuf':         'Necessário + Suficiente (≡ definido)',
    'det.src_defs':       'Definições das Fontes',
    'det.linked_cqs':     'Questões de Competência Vinculadas',
    'det.owl_preview':    'Pré-visualização OWL / Turtle',
    'det.fol_theory':     'Teoria FOL Gerada',
    'det.validate_btn':   '✓ Validar',
    'det.export_btn':     '⬇ Exportar Turtle',
    'det.expert_review':  'Revisão do especialista',
    'det.expert_ph':      'Discordância ou nota do especialista (opcional)...',
    'det.pending':        'Pendente',
    'det.accepted':       'Aceito',
    'det.disputed':       'Contestado',
    'det.revised':        'Revisado',

    // ── Annotations ──────────────────────────────────────────────────
    'ann.comments':       '💬 Comentários',
    'ann.add_ph':         'Adicionar um comentário…',
    'ann.post':           'Publicar',
    'ann.resolve':        '✓ Resolver',
    'ann.delete':         'Excluir',
    'ann.resolved':       '✓ resolvido',
    'ann.comment_s':      'comentário',
    'ann.comment_pl':     'comentários',

    // ── Relations ────────────────────────────────────────────────────
    'rel.title':          'Relações OWL',
    'rel.new':            'Nova Relação',
    'rel.name':           'Nome',
    'rel.type':           'Tipo',
    'rel.domain':         'Domínio',
    'rel.range':          'Alcance',
    'rel.status':         'Status',
    'rel.used_in':        'Usada em',
    'rel.save':           'Salvar',
    'rel.cancel':         'Cancelar',
    'rel.delete':         'Excluir',

    // ── Q&A ──────────────────────────────────────────────────────────
    'qa.title':           'P&R sobre a Ontologia',
    'qa.sub':             'Pergunte sobre classes COPPP, BFO 2020 ou IOF-Core',
    'qa.placeholder':     'Pergunte sobre COPPP, BFO 2020 ou IOF-Core…',
    'qa.send':            'Enviar',
    'qa.clear':           'Limpar',
    'qa.empty':           'Faça qualquer pergunta sobre a ontologia',

    // ── Verify ───────────────────────────────────────────────────────
    'ver.title':          'Verificação',
    'ver.run_oops':       'Executar OOPS!',
    'ver.run_foops':      'Executar FOOPS!',
    'ver.consistency':    'Verificar Consistência',

    // ── Imported Ontologies ──────────────────────────────────────
    'nav.imported_onto':  'Ontologias',
    'onto.title':         'Ontologias Importadas',
    'onto.sub':           'Navegue pelas classes BFO 2020 e IOF-Core com suas definições e axiomas',
    'onto.search_ph':     'Buscar classes…',
    'onto.all':           'Todas',
    'onto.bfo_only':      'Somente BFO',
    'onto.iof_only':      'Somente IOF-Core',
    'onto.both':          'Ambas',
    'onto.classes':       'classes',
    'onto.select':        'Selecione uma classe à esquerda para ver seus detalhes.',
    'onto.definition':    'Definição',
    'onto.nl_def':        'Definição em Linguagem Natural',
    'onto.semiformal':    'Definição Semi-Formal (LN)',
    'onto.fol_def':       'Definição em Lógica de Primeira Ordem',
    'onto.fol_axiom':     'Axioma em Lógica de Primeira Ordem',
    'onto.semiformal_ax': 'Axioma Semi-Formal (LN)',
    'onto.example':       'Exemplo',
    'onto.counter_ex':    'Contra-Exemplo',
    'onto.scope':         'Nota de Escopo',
    'onto.expl_note':     'Nota Explicativa',
    'onto.usage':         'Nota de Uso',
    'onto.prim_rat':      'Justificativa Primitiva',
    'onto.parents':       'Superclasses',
    'onto.children':      'Subclasses',
    'onto.disjoints':     'Disjunto com',
    'onto.adapted':       'Adaptado de',
    'onto.id':            'Identificador',
    'onto.primitive':     'Primitiva',

    // ── Suggestion box ───────────────────────────────────────────────
    'suggest.fab':         'Sugerir mudança',
    'suggest.title':       'Sugerir uma mudança',
    'suggest.hint':        'Abre uma issue pré-preenchida no repositório do COPI — nada é enviado até você confirmar lá.',
    'suggest.field_title': 'Título',
    'suggest.field_desc':  'Descrição',
    'suggest.title_ph':    'p.ex. A ordenação da busca parece estranha para termos no plural',
    'suggest.desc_ph':     'O que você mudaria, e por quê?',
    'suggest.cancel':      'Cancelar',
    'suggest.submit':      'Abrir issue no GitHub ↗',
  }
};

// ── Core apply function ──────────────────────────────────────────────────────
function applyTranslations(lang) {
  const dict = TRANSLATIONS[lang];
  if (!dict) return;

  document.querySelectorAll('[data-i18n]').forEach(el => {
    const key = el.dataset.i18n;
    const val = dict[key];
    if (val === undefined) return;

    if (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') {
      if (el.getAttribute('placeholder')) el.placeholder = val;
      else el.value = val;
    } else if (el.tagName === 'OPTION') {
      el.textContent = val;
    } else {
      // Preserve inner HTML for elements with icons (e.g. "⬇ Baixar")
      // but only if the key value contains HTML entities or tags
      if (val.includes('<') || val.includes('&')) {
        el.innerHTML = val;
      } else {
        el.textContent = val;
      }
    }
  });

  // Also translate placeholder-only inputs
  document.querySelectorAll('[data-i18n-ph]').forEach(el => {
    const key = el.dataset.i18nPh;
    const val = dict[key];
    if (val !== undefined) el.placeholder = val;
  });
}

// ── Public translation function for JS-generated HTML ───────────────────────
window._t = function(key) {
  const lang = localStorage.getItem('coppp_lang') || 'en';
  if (lang === 'en') return null;
  return TRANSLATIONS[lang]?.[key] ?? null;
};

// Shorthand: returns translation or English fallback
window._T = function(key, fallback) {
  return window._t(key) || fallback;
};

// ── Language toggle ──────────────────────────────────────────────────────────
window.toggleLang = function() {
  const current = localStorage.getItem('coppp_lang') || 'en';
  const next = current === 'en' ? 'pt' : 'en';
  localStorage.setItem('coppp_lang', next);
  location.reload();
};

// ── Init on DOM ready ────────────────────────────────────────────────────────
(function() {
  const lang = localStorage.getItem('coppp_lang') || 'en';

  // Update toggle button label immediately (before DOMContentLoaded)
  // so there's no flash — the button text is set after content loads
  document.addEventListener('DOMContentLoaded', function() {
    const btn = document.getElementById('lang-toggle-btn');
    if (btn) btn.textContent = lang === 'pt' ? 'EN' : 'PT';
    applyTranslations(lang);
  });
})();
