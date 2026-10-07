// Configurações · Conexões: lista, detalhe com formulário, teste, default, schema-sync e exclusão.
// Cada conexão é um repositório git (clone local; sem remote_url = só local). `review_mode`
// decide como as mudanças são publicadas: direto na branch principal, ou por PR.
import { api } from '../api.js';
import { go, hrefs } from '../router.js';

const blankForm = () => ({
  name: '',
  remote_url: '',
  review_mode: 'direct',
  enabled: true,
});

export function register(Alpine) {
  Alpine.data('connectionsView', () => ({
    form: blankForm(),
    loading: false,
    saving: false,
    testing: false,
    syncing: false,
    deleting: false,
    error: null,
    notFound: false,
    alert: null, // { kind: 'ok' | 'error', message, latency }
    plan: null, // resultado do dry-run do schema-sync
    syncMessage: null,
    confirmName: '',

    get app() {
      return Alpine.store('app');
    },
    get sub() {
      return this.app.route.params.sub;
    },
    get isNew() {
      return this.sub === 'new';
    },
    get conn() {
      return this.sub && !this.isNew ? this.app.connections.find((c) => c.id === this.sub) || null : null;
    },
    get editable() {
      return !this.conn?.is_catalog;
    },
    get canDelete() {
      return !!this.conn && !this.conn.is_catalog && !this.conn.is_default;
    },
    get dangerReady() {
      return this.canDelete && this.confirmName === this.conn.name;
    },
    get planEmpty() {
      const p = this.plan;
      return !!p && !p.tables_created.length && !p.columns_added.length && !p.indexes_created.length && !p.fts_created;
    },
    get canApply() {
      return !!this.plan && !this.planEmpty && !this.plan.pending_manual.length;
    },

    async init() {
      await this.load();
      this.$watch('$store.app.route.params.sub', () => this.load());
    },

    async load() {
      this.error = null;
      this.notFound = false;
      this.alert = null;
      this.plan = null;
      this.syncMessage = null;
      this.confirmName = '';
      this.loading = true;
      try {
        await this.app.loadConnections();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
      if (this.isNew) {
        this.form = blankForm();
      } else if (this.sub) {
        if (this.app.connError) return;
        const c = this.conn;
        if (!c) {
          this.notFound = true;
          return;
        }
        this.fill(c);
      }
    },

    fill(c) {
      this.form = {
        name: c.name,
        remote_url: c.remote_url || '',
        review_mode: c.review_mode || 'direct',
        enabled: c.enabled,
      };
    },

    /** Recarrega a lista sem mexer no formulário (último teste, default, enabled). */
    async refreshList() {
      try {
        await this.app.loadConnections();
      } catch (e) {
        this.error = e.message;
      }
    },

    // ---- apresentação ----
    target(c) {
      return c.remote_url || 'Local-only repository (no remote)';
    },
    dotClass(c) {
      if (!c.enabled) return 'off';
      if (!c.last_test) return 'off';
      return c.last_test.status === 'ok' ? '' : 'err';
    },
    lastTest(c) {
      const t = c.last_test;
      if (!t) return 'Never tested';
      return t.status === 'ok' ? `OK · ${t.latency_ms} ms` : 'Failed on last test';
    },

    // ---- corpo da requisição ----
    buildBody() {
      const f = this.form;
      return {
        name: f.name.trim(),
        remote_url: f.remote_url.trim() || null,
        review_mode: f.review_mode,
        enabled: !!f.enabled,
      };
    },

    /** Grava (POST ou PATCH) e devolve a conexão salva. */
    async persist() {
      const creating = this.isNew;
      this.error = null;
      this.saving = true;
      try {
        const body = this.buildBody();
        const saved = creating
          ? await api('POST', '/connections', { body })
          : await api('PATCH', `/connections/${encodeURIComponent(this.sub)}`, { body });
        await this.app.loadConnections();
        if (creating) go(hrefs.connections(saved.id));
        else this.fill(this.conn || saved);
        return saved;
      } catch (e) {
        this.error = e.message;
        return null;
      } finally {
        this.saving = false;
      }
    },

    async save() {
      const creating = this.isNew;
      const saved = await this.persist();
      if (saved) this.app.toast(creating ? 'Connection created' : 'Connection saved');
    },

    async saveAndTest() {
      const saved = await this.persist();
      if (!saved) return;
      await this.runTest(saved.id);
    },

    async test() {
      await this.runTest(this.conn.id);
    },

    async runTest(id) {
      this.testing = true;
      this.alert = null;
      try {
        const r = await api('POST', `/connections/${encodeURIComponent(id)}/test`);
        this.alert = { kind: r.status === 'ok' ? 'ok' : 'error', message: r.message || r.status, latency: r.latency_ms };
        await this.refreshList();
      } catch (e) {
        this.alert = { kind: 'error', message: e.message, latency: null };
      } finally {
        this.testing = false;
      }
    },

    async makeDefault() {
      this.error = null;
      try {
        await api('PUT', `/connections/${encodeURIComponent(this.conn.id)}/default`);
        await this.refreshList();
        this.app.toast('Connection set as default');
      } catch (e) {
        this.error = e.message;
      }
    },

    // ---- schema-sync: dry-run primeiro, depois aplica ----
    async syncSchema(dryRun) {
      this.error = null;
      this.syncMessage = null;
      this.syncing = true;
      try {
        const id = encodeURIComponent(this.conn.id);
        const r = await api('POST', `/connections/${id}/schema-sync`, { query: { dry_run: dryRun ? 'true' : 'false' } });
        if (dryRun) {
          this.plan = r;
        } else {
          this.plan = null;
          this.syncMessage = `Schema synced (${r.status}).`;
          this.app.toast('Schema synced');
        }
      } catch (e) {
        this.error = e.message;
      } finally {
        this.syncing = false;
      }
    },

    // ---- zona de perigo ----
    async remove() {
      if (!this.dangerReady) return;
      this.error = null;
      this.deleting = true;
      const id = this.conn.id;
      try {
        await api('DELETE', `/connections/${encodeURIComponent(id)}`);
        await this.app.loadConnections();
        if (this.app.connId === id) {
          const next = this.app.connections.find((c) => c.is_default) || this.app.connections[0];
          if (next) await this.app.selectConnection(next.id);
        }
        this.app.toast('Connection deleted');
        go(hrefs.connections());
      } catch (e) {
        this.error = e.message;
      } finally {
        this.deleting = false;
      }
    },
  }));
}
