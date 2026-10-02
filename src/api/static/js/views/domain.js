// Página de Domain: lista de itens com summary, filtro por type.
import { api } from '../api.js';
import { parseDate } from '../util.js';

export function register(Alpine) {
  Alpine.data('domainView', () => ({
    items: [],
    loading: false,
    error: null,
    typeFilter: '',
    sort: 'title',
    seq: 0,

    get app() {
      return Alpine.store('app');
    },
    init() {
      this.$watch(
        () => this.app.route.params.dm + '|' + this.app.treeWs,
        () => this.load(),
      );
      this.load();
    },
    async load() {
      const dm = this.app.route.params.dm;
      if (!dm) return;
      const seq = ++this.seq;
      this.loading = true;
      this.error = null;
      try {
        const items = await api('GET', '/items', { query: { domain_id: dm, limit: 200 } });
        if (seq === this.seq) this.items = items;
      } catch (e) {
        if (seq === this.seq && e.status !== 401) this.error = e.message;
      } finally {
        if (seq === this.seq) this.loading = false;
      }
    },
    get types() {
      return [...new Set(this.items.map((i) => i.type))].sort();
    },
    get filtered() {
      const list = this.typeFilter ? this.items.filter((i) => i.type === this.typeFilter) : this.items.slice();
      if (this.sort === 'recent') {
        return list.sort((a, b) => (parseDate(b.updated_at)?.getTime() || 0) - (parseDate(a.updated_at)?.getTime() || 0));
      }
      return list.sort((a, b) => a.title.localeCompare(b.title, 'pt-BR'));
    },
  }));
}
