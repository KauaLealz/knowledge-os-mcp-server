// Configurações · Conexões: lista, detalhe com edição, teste, padrão e exclusão. A saúde
// (`GET /connections/health`) mostra o caminho da pasta e os `.md` que a leitura ignorou.
// Cada conexão é um repositório git numa pasta local. `review_mode` decide como as
// mudanças são publicadas: direto na branch principal, ou por PR. A UI não cria
// conexão: a criação é pelo MCP (`connection_create`).
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
    deleting: false,
    error: null,
    notFound: false,
    alert: null, // { kind: 'ok' | 'error', message, latency }
    confirmName: '',
    health: {}, // id -> { path, ok, parse_errors: [{ path, error }] }

    get app() {
      return Alpine.store('app');
    },
    get sub() {
      return this.app.route.params.sub;
    },
    get conn() {
      return this.sub ? this.app.connections.find((c) => c.id === this.sub) || null : null;
    },
    get dangerReady() {
      return !!this.conn && this.confirmName === this.conn.name;
    },
    async init() {
      await this.load();
      this.$watch('$store.app.route.params.sub', () => this.load());
    },

    async load() {
      this.error = null;
      this.notFound = false;
      this.alert = null;
      this.confirmName = '';
      this.loading = true;
      try {
        await this.app.loadConnections();
        await this.loadHealth();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.loading = false;
      }
      if (!this.sub) {
        this.form = blankForm();
      } else {
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

    async loadHealth() {
      try {
        const rows = await api('GET', '/connections/health');
        this.health = Object.fromEntries(rows.map((h) => [h.id, h]));
      } catch {
        this.health = {}; // a lista continua útil sem a saúde
      }
    },
    parseErrors(c) {
      return this.health[c.id]?.parse_errors || [];
    },

    // ---- apresentação (os badges vêm de connectionBadges, em util.js) ----
    dotClass(c) {
      if (!c.enabled) return 'off';
      if (!c.last_test) return 'off';
      return c.last_test.status === 'ok' ? '' : 'err';
    },
    lastTest(c) {
      const t = c.last_test;
      if (!t) return 'Never tested';
      return t.status === 'ok' ? `OK · ${t.latency_ms} ms` : 'Failed the last test';
    },
    /** How changes are published (`review_mode`): straight to the main branch or by PR. */
    modeLabel(mode) {
      return mode === 'pr' ? 'Publishes by pull request' : 'Publishes directly';
    },

    // ---- corpo da requisição ----
    buildBody() {
      const f = this.form;
      return {
        name: f.name.trim(),
        remote_url: (f.remote_url || '').trim() || null,
        review_mode: f.review_mode,
        enabled: !!f.enabled,
      };
    },

    /** Grava a edição (PATCH) e devolve a conexão salva. */
    async persist() {
      this.error = null;
      this.saving = true;
      try {
        const body = this.buildBody();
        const saved = await api('PATCH', `/connections/${encodeURIComponent(this.sub)}`, { body });
        await this.app.loadConnections();
        this.fill(this.conn || saved);
        return saved;
      } catch (e) {
        this.error = e.message;
        return null;
      } finally {
        this.saving = false;
      }
    },

    async save() {
      const saved = await this.persist();
      if (saved) this.app.toast('Connection saved');
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
        this.app.toast('Default connection set');
      } catch (e) {
        this.error = e.message;
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
        this.app.toast('Connection removed');
        go(hrefs.connections());
      } catch (e) {
        this.error = e.message;
      } finally {
        this.deleting = false;
      }
    },
  }));
}
