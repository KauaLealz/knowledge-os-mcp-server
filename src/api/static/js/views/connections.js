// Configurações · Conexões: lista, detalhe com formulário, teste, default, schema-sync e exclusão.
// A senha é só de escrita: vai no corpo de POST/PATCH quando preenchida e é limpa ao salvar.
// Ela nunca é lida de volta, guardada em storage, escrita em log, toast ou URL.
import { api } from '../api.js';
import { go, hrefs } from '../router.js';

const blankForm = () => ({
  name: '',
  db_type: 'sqlite',
  path: '',
  host: 'localhost',
  port: '',
  database: '',
  username: '',
  enabled: true,
});

const DEFAULT_PORTS = { postgresql: 5432, mysql: 3306 };

export function register(Alpine) {
  Alpine.data('connectionsView', () => ({
    form: blankForm(),
    password: '', // só escrita: nunca preenchido a partir da API
    removePassword: false,
    passwordSet: false,
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
      this.password = '';
      this.removePassword = false;
      this.passwordSet = false;
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
        db_type: c.db_type,
        path: c.path || '',
        host: c.host || '',
        port: c.port ?? '',
        database: c.database || '',
        username: c.username || '',
        enabled: c.enabled,
      };
      this.passwordSet = !!c.password_set;
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
      if (c.is_catalog || c.db_type === 'sqlite') return c.path || '—';
      return `${c.host}:${c.port ?? DEFAULT_PORTS[c.db_type] ?? ''}/${c.database}`;
    },
    dotClass(c) {
      if (!c.enabled) return 'off';
      if (!c.last_test) return 'off';
      return c.last_test.status === 'ok' ? '' : 'err';
    },
    lastTest(c) {
      const t = c.last_test;
      if (!t) return 'Nunca testada';
      return t.status === 'ok' ? `OK · ${t.latency_ms} ms` : 'Falhou no último teste';
    },

    // ---- corpo da requisição ----
    buildBody(creating) {
      const f = this.form;
      const body = { name: f.name.trim(), enabled: !!f.enabled };
      if (creating) body.db_type = f.db_type;
      if (f.db_type === 'sqlite') {
        body.path = f.path.trim();
      } else {
        body.host = f.host.trim();
        body.port = f.port === '' || f.port === null ? null : Number(f.port);
        body.database = f.database.trim();
        body.username = f.username.trim() || null;
      }
      // Só vai quando preenchida; "remover senha" envia null; ausente mantém a atual.
      if (this.password) body.password = this.password;
      else if (!creating && this.removePassword) body.password = null;
      return body;
    },

    /** Grava (POST ou PATCH) e devolve a conexão salva. Limpa o campo de senha ao final. */
    async persist() {
      const creating = this.isNew;
      this.error = null;
      this.saving = true;
      try {
        const body = this.buildBody(creating);
        const saved = creating
          ? await api('POST', '/connections', { body })
          : await api('PATCH', `/connections/${encodeURIComponent(this.sub)}`, { body });
        this.password = '';
        this.removePassword = false;
        await this.app.loadConnections();
        if (creating) go(hrefs.connections(saved.id));
        else this.fill(this.conn || saved);
        return saved;
      } catch (e) {
        this.error = e.message;
        return null;
      } finally {
        this.password = '';
        this.saving = false;
      }
    },

    async save() {
      const creating = this.isNew;
      const saved = await this.persist();
      if (saved) this.app.toast(creating ? 'Conexão criada' : 'Conexão salva');
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
        this.app.toast('Conexão definida como default');
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
          this.syncMessage = `Schema sincronizado (${r.status}).`;
          this.app.toast('Schema sincronizado');
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
        this.app.toast('Conexão excluída');
        go(hrefs.connections());
      } catch (e) {
        this.error = e.message;
      } finally {
        this.deleting = false;
      }
    },
  }));
}
