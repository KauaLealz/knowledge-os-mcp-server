// Shared logic for item listings (Workspace, Project and Subject pages): paged loading,
// type and subtype chips (multi-select), server search and project/subject filters. Filter
// state lives in Alpine.store('app').filters (survives navigation). Items in `review` are
// marked ⚠ and listed after the others (as search does).
import { api } from '../api.js';
import { TYPE_ORDER, isReview, parseDate, subtypeLabel, subtypesOf, typeLabel } from '../util.js';

export const PAGE_SIZE = 50; // items per page (same size as search)
const SEARCH_LIMIT = 50; // max accepted by search
const MIN_QUERY = 2;

const time = (it) => parseDate(it.updated_at)?.getTime() || 0;

/** Copies getters/setters too (a plain object spread would evaluate the getters). */
export function mix(view, mixin) {
  return Object.defineProperties(view, Object.getOwnPropertyDescriptors(mixin));
}

/**
 * The view must provide: `scope()` -> { workspace_id, project_id? } and `Alpine` (via `store`).
 * Optional: `sort` ('title' | 'recent').
 */
export function listingMixin(Alpine) {
  let timer = null; // outside reactive state
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
    sort: 'recent', // listing defaults to most-recently-updated first

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
        this.filters.subtypes.length > 0 ||
        this.filters.projectIds.length > 0 ||
        this.filters.subjectIds.length > 0
      );
    },

    initListing() {
      this.$watch(
        () => this.filters.q + '|' + this.filters.types.join(',') + '|' + this.filters.subtypes.join(',') + '|' + JSON.stringify(this.scope()),
        () => this.runSearch(),
      );
      // project/subject filter on the server (not just the loaded page, like type does) —
      // changing either reloads page 1 with the new filter.
      this.$watch(
        () => this.filters.projectIds.join(',') + '|' + this.filters.subjectIds.join(',') + '|' + JSON.stringify(this.scope()),
        () => {
          this.runSearch();
          if (!this.searchMode) this.goToPage(1);
        },
      );
      this.runSearch();
    },

    /** Initial load (or reload on workspace/project change): fetches page 1. */
    async loadItems() {
      await this.goToPage(1);
    },

    get totalPages() {
      return Math.max(1, Math.ceil(this.total / this.pageSize));
    },

    /** Fetches a specific page and replaces the displayed list (no accumulation). */
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
          if (this.filters.subtypes.length) q.subtypes = this.filters.subtypes.join(',');
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

    // ---- type chips ----
    toggleType(t) {
      const cur = this.filters.types;
      this.filters.types = cur.includes(t) ? cur.filter((x) => x !== t) : [...cur, t];
      // subtipo de um tipo que saiu do filtro não faz mais sentido
      const keep = new Set(this.filters.types.flatMap((x) => subtypesOf(x)));
      if (this.filters.types.length) this.filters.subtypes = this.filters.subtypes.filter((x) => keep.has(x));
    },
    toggleSubtype(st) {
      const cur = this.filters.subtypes;
      this.filters.subtypes = cur.includes(st) ? cur.filter((x) => x !== st) : [...cur, st];
    },
    clearFilters() {
      this.filters.q = '';
      this.filters.types = [];
      this.filters.subtypes = [];
      this.filters.projectIds = [];
      this.filters.subjectIds = [];
    },

    // ---- project/subject filter (multi-select, filters on the server) ----
    toggleProjectFilter(id) {
      const cur = this.filters.projectIds;
      this.filters.projectIds = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    },
    toggleSubjectFilter(id) {
      const cur = this.filters.subjectIds;
      this.filters.subjectIds = cur.includes(id) ? cur.filter((x) => x !== id) : [...cur, id];
    },
    /** Workspace: every project in the tree. Project: none (already a single project — a
     * project filter there would be redundant). */
    get projectFilterOptions() {
      if (this.scope().project_id) return [];
      return (this.app.tree?.projects || []).map((p) => ({ id: p.id, name: p.name }));
    },
    /** Workspace: subjects across all projects, with the project name alongside (to tell
     * apart a "Credentials" subject from one project vs. another's). Project: only that
     * project's subjects, no need to repeat its name. Subject: none — already a single
     * subject, a filter there would be redundant with the page itself. */
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
    /** Chips: with a count in the listing; in search mode, every type (the count comes
     * from the result groups). */
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

    /** Subtype chips: the subtypes of the chosen types (or of every type present), with a
     * count in the listing. */
    get chipSubtypes() {
      const types = this.filters.types.length ? this.filters.types : TYPE_ORDER;
      const counts = {};
      for (const it of this.items) if (it.subtype) counts[it.subtype] = (counts[it.subtype] || 0) + 1;
      const all = [...new Set(types.flatMap((t) => subtypesOf(t)))];
      const shown = this.searchMode ? all : all.filter((st) => counts[st] || this.filters.subtypes.includes(st));
      return shown.map((st) => ({ subtype: st, label: subtypeLabel(st), count: this.searchMode ? null : counts[st] || 0 }));
    },

    // ---- displayed list: a single flat list, sorted — no grouping by type ----
    get visible() {
      if (this.searchMode) return this.remote;
      const sel = this.filters.types;
      const sub = this.filters.subtypes;
      let list = sel.length ? this.items.filter((i) => sel.includes(i.type)) : this.items.slice();
      if (sub.length) list = list.filter((i) => sub.includes(i.subtype));
      const byReview = (a, b) => Number(isReview(a)) - Number(isReview(b));
      if (this.sort === 'recent') return list.sort((a, b) => byReview(a, b) || time(b) - time(a));
      return list.sort((a, b) => byReview(a, b) || a.title.localeCompare(b.title));
    },
    /** Where the item lives: search returns `where` ("Workspace/Project"); the listing has the
     * project id (resolved via the tree). */
    where(it) {
      return it.where || it.project || this.app.tree?.projects?.find((p) => p.id === it.project_id)?.name || '';
    },
  };
}
