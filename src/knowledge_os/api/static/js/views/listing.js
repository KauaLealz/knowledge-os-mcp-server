// Lógica compartilhada das listas de itens (telas de Workspace e de Project): carga da
// listagem, chips de tipo (multi-seleção), busca no servidor e agrupamento por tipo.
// O estado dos filtros vive em Alpine.store('app').filters (não se perde ao navegar).
import { api } from '../api.js';
import { TYPE_ORDER, groupByType, parseDate, typeLabel } from '../util.js';

export const LIMIT = 500; // máximo aceito pela API na listagem
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
    remote: [],
    searching: false,
    searchError: null,
    sort: 'title',

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
      return this.searchMode || this.filters.types.length > 0;
    },

    initListing() {
      this.$watch(
        () => this.filters.q + '|' + this.filters.types.join(',') + '|' + JSON.stringify(this.scope()),
        () => this.runSearch(),
      );
      this.runSearch();
    },

    async loadItems() {
      const scope = this.scope();
      if (!scope.workspace_id) return;
      const seq = ++loadSeq;
      this.loading = true;
      this.error = null;
      try {
        const items = await api('GET', '/items', { query: { ...scope, limit: LIMIT } });
        if (seq === loadSeq) this.items = items;
      } catch (e) {
        if (seq === loadSeq) this.error = e.message;
      } finally {
        if (seq === loadSeq) this.loading = false;
      }
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
      return it.project || this.app.tree?.projects.find((p) => p.id === it.project_id)?.name || '';
    },
  };
}
