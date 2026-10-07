// Lógica compartilhada das listas de itens (telas de Workspace e de Project): carga da
// listagem, chips de tipo (multi-seleção), busca no servidor e agrupamento por tipo.
// O estado dos filtros vive em Alpine.store('app').filters (não se perde ao navegar).
import { api } from '../api.js';
import { TYPE_ORDER, groupByType, parseDate, typeLabel } from '../util.js';

export const PAGE_SIZE = 50; // itens por página (mesmo tamanho da busca)
const SEARCH_LIMIT = 50; // máximo aceito pela busca
const MIN_QUERY = 2;

const time = (it) => parseDate(it.updated_at)?.getTime() || 0;

/** Copia getters/setters junto (o spread de objeto avaliaria os getters). */
export function mix(view, mixin) {
  return Object.defineProperties(view, Object.getOwnPropertyDescriptors(mixin));
}

/**
 * A view precisa fornecer: `scope()` -> { workspace_id, project_id? } e `Alpine` (via `store`).
 * Opcional: `sort` ('title' | 'recent').
 */
export function listingMixin(Alpine) {
  let timer = null; // fora do estado reativo
  let searchSeq = 0;
  let loadSeq = 0;
  return {
    items: [],
    loading: false,
    error: null,
    pageSize: PAGE_SIZE,
    page: 1,
    total: 0,
    remote: [],
    searching: false,
    searchError: null,
    sort: 'recent', // listagem geral por padrão ordenada pelo mais atualizado

    get app() {
      return Alpine.store('app');
    },
    get filters() {
      return this.app.filters;
    },
    get query() {
      return this.filters.q.trim();
    },
    get searchMode() {
      return this.query.length >= MIN_QUERY;
    },
    get filtering() {
      return (
        this.searchMode ||
        this.filters.types.length > 0 ||
        this.filters.projectIds.length > 0 ||
        this.filters.subjectIds.length > 0
      );
    },

    initListing() {
      this.$watch(
        () => this.filters.q + '|' + this.filters.types.join(',') + '|' + JSON.stringify(this.scope()),
        () => this.runSearch(),
      );
      // project/assunto filtram no servidor (não só a página carregada, como o tipo) —
      // mudar qualquer um dos dois recarrega a página 1 com o filtro novo.
      this.$watch(
        () => this.filters.projectIds.join(',') + '|' + this.filters.subjectIds.join(',') + '|' + JSON.stringify(this.scope()),
        () => {
          this.runSearch();
          if (!this.searchMode) this.goToPage(1);
        },
      );
      this.runSearch();
    },

    /** Carga inicial (ou recarga ao trocar de workspace/project): busca a página 1. */
    async loadItems() {
      await this.goToPage(1);
    },

    get totalPages() {
      return Math.max(1, Math.ceil(this.total / this.pageSize));
    },

    /** Busca uma página específica e substitui a lista exibida (sem acumular). */
    async goToPage(n) {
      const scope = this.scope();
      if (!scope.workspace_id) return;
      const target = Math.min(Math.max(1, n), this.total ? this.totalPages : n);
      const seq = ++loadSeq;
      this.loading = true;
      this.error = null;
      try {
        const query = { ...scope, limit: this.pageSize, offset: (target - 1) * this.pageSize };
        if (this.filters.projectIds.length) query.project_id = this.filters.projectIds.join(',');
        if (this.filters.subjectIds.length) query.subject_id = this.filters.subjectIds.join(',');
        const res = await api('GET', '/items', { query });
        if (seq === loadSeq) {
          this.items = res.items;
          this.total = res.total;
          this.page = target;
        }
      } catch (e) {
        if (seq === loadSeq) this.error = e.message;
      } finally {
        if (seq === loadSeq) this.loading = false;
      }
    },
    prevPage() {
      if (this.page > 1) this.goToPage(this.page - 1);
    },
    nextPage() {
      if (this.page < this.totalPages) this.goToPage(this.page + 1);
    },

    runSearch() {
      clearTimeout(timer);
      const mine = ++searchSeq;
      this.searchError = null;
      if (!this.searchMode) {
        this.remote = [];
        this.searching = false;
        return;
      }
      this.searching = true;
      timer = setTimeout(async () => {
        try {
          const q = { ...this.scope(), query: this.query, limit: SEARCH_LIMIT };
          if (this.filters.types.length) q.types = this.filters.types.join(',');
          if (this.filters.projectIds.length) q.project_id = this.filters.projectIds.join(',');
          if (this.filters.subjectIds.length) q.subject_id = this.filters.subjectIds.join(',');
          const res = await api('GET', '/items/search', { query: q });
          if (mine === searchSeq) this.remote = res.results;
        } catch (e) {
          if (mine === searchSeq) {
            this.remote = [];
            this.searchError = e.message;
          }
        } finally {
          if (mine === searchSeq) this.searching = false;
        }
      }, 250);
    },

    // ---- chips de tipo ----
    toggleType(t) {
      const cur = this.filters.types;
      this.filters.types = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
    },
    clearTypes() {
      this.filters.types = [];
    },
    clearFilters() {
      this.filters.q = '';
      this.filters.types = [];
      this.filters.projectIds = [];
      this.filters.subjectIds = [];
    },

    // ---- filtro por project/assunto (multisseleção, filtra no servidor) ----
    toggleProjectFilter(id) {
      const cur = this.filters.projectIds;
      this.filters.projectIds = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    },
    toggleSubjectFilter(id) {
      const cur = this.filters.subjectIds;
      this.filters.subjectIds = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    },
    /** Workspace: todo project da árvore. Project: nenhum (já é um project só, o filtro de
     * project ali seria redundante). */
    get projectFilterOptions() {
      if (this.scope().project_id) return [];
      return (this.app.tree?.projects || []).map((p) => ({ id: p.id, name: p.name }));
    },
    /** Workspace: assuntos de todos os projects, com o nome do project junto (pra
     * diferenciar "Credenciais" de um project do "Credenciais" de outro). Project: só os
     * assuntos do próprio project, sem precisar repetir o nome dele. Subject: nenhum — já
     * é um assunto só, o filtro ali seria redundante com a própria página. */
    get subjectFilterOptions() {
      if (this.scope().subject_id) return [];
      const pid = this.scope().project_id;
      const projects = (this.app.tree?.projects || []).filter((p) => !pid || p.id === pid);
      const out = [];
      for (const p of projects) {
        for (const s of p.subjects || []) {
          out.push({ id: s.id, name: pid ? s.name : `${s.name} · ${p.name}` });
        }
      }
      return out;
    },
    /** Chips: com contagem na listagem; na busca, todos os tipos (a contagem vem dos grupos). */
    get chipTypes() {
      const counts = {};
      for (const it of this.items) counts[it.type] = (counts[it.type] || 0) + 1;
      const present = TYPE_ORDER.filter((t) => counts[t] || this.filters.types.includes(t));
      const types = this.searchMode ? TYPE_ORDER.filter((t) => t !== 'secret' || present.includes(t)) : present;
      return types.map((t) => ({
        type: t,
        label: typeLabel(t),
        count: this.searchMode ? null : counts[t] || 0,
      }));
    },

    // ---- lista exibida ----
    get visible() {
      if (this.searchMode) return this.remote;
      const sel = this.filters.types;
      const list = sel.length ? this.items.filter((i) => sel.includes(i.type)) : this.items.slice();
      if (this.sort === 'recent') return list.sort((a, b) => time(b) - time(a));
      return list.sort((a, b) => a.title.localeCompare(b.title, 'pt-BR'));
    },
    get groups() {
      return groupByType(this.visible);
    },
    /** Project do item: a busca devolve o nome; a listagem só o id (resolvido pela árvore). */
    where(it) {
      return it.project || this.app.tree?.projects?.find((p) => p.id === it.project_id)?.name || '';
    },
  };
}
