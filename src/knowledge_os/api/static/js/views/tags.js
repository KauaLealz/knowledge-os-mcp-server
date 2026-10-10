// Tags gerenciadas da conexão: lista com contagem, criar, renomear (mescla se o nome novo já
// existe) e apagar — o apagar pede a prévia ao servidor (quantos itens perdem a tag) e só
// remove no segundo clique, com `confirm=true`.
import { api } from '../api.js';

const enc = encodeURIComponent;

export function register(Alpine) {
  Alpine.data('tagsView', () => ({
    newNames: '',
    editing: null, // nome da tag em edição
    newName: '',
    pending: null, // { name, items }: prévia do apagar, aguardando confirmação
    busy: false,
    error: null,

    get app() {
      return Alpine.store('app');
    },
    get tags() {
      return this.app.tags;
    },

    init() {
      this.app.loadTags();
      this.$watch('$store.app.connId', () => this.app.loadTags());
    },

    async run(fn) {
      if (this.busy) return;
      this.busy = true;
      this.error = null;
      try {
        await fn();
        await this.app.loadTags();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },

    create() {
      const names = this.newNames.split(',').map((x) => x.trim()).filter(Boolean);
      if (!names.length) return;
      return this.run(async () => {
        const r = await api('POST', '/tags', { body: { names } });
        this.newNames = '';
        this.app.toast(r.created.length ? `Created: ${r.created.join(', ')}` : 'Already existed');
      });
    },

    startRename(t) {
      this.editing = t.name;
      this.newName = t.name;
      this.pending = null;
    },
    rename() {
      const from = this.editing;
      const to = this.newName.trim();
      if (!from || !to || to === from) {
        this.editing = null;
        return;
      }
      return this.run(async () => {
        const r = await api('PUT', `/tags/${enc(from)}`, { body: { new_name: to } });
        this.editing = null;
        this.app.toast(`${r.merged ? 'Merged' : 'Renamed'} in ${r.renamed} item(s)`);
        this.app.refresh();
      });
    },

    /** Primeiro clique: prévia (`DELETE` sem confirm). Segundo: apaga de verdade. */
    remove(t) {
      if (this.pending?.name === t.name) {
        return this.run(async () => {
          await api('DELETE', `/tags/${enc(t.name)}`, { query: { confirm: 'true' } });
          this.pending = null;
          this.app.toast(`Tag ${t.name} deleted`);
          this.app.refresh();
        });
      }
      return this.run(async () => {
        const r = await api('DELETE', `/tags/${enc(t.name)}`);
        this.pending = r.tags?.[0] || { name: t.name, items: t.count };
      });
    },
    cancel() {
      this.pending = null;
      this.editing = null;
    },
  }));
}
