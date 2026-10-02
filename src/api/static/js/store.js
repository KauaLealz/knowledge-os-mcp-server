// Store global (Alpine.store('app')): conexão, workspaces, árvore, rota, tema e toasts.
import { api, setConnection, setOnExpired } from './api.js';
import { parseHash, hrefs, go } from './router.js';
import { lsGet, lsSet } from './util.js';

const THEMES = ['system', 'light', 'dark'];

export function applyTheme(theme) {
  const root = document.documentElement;
  if (theme === 'light' || theme === 'dark') root.setAttribute('data-theme', theme);
  else root.removeAttribute('data-theme');
}

function readJson(key, fallback) {
  try {
    return JSON.parse(lsGet(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Tolerante a campos que a API ainda pode não ter (enabled/is_default). */
function normalizeConnection(c) {
  return {
    id: c.id,
    name: c.name || c.id,
    db_type: c.db_type || '',
    enabled: c.enabled ?? c.is_active ?? true,
    is_default: !!c.is_default,
    password_set: c.password_set,
  };
}

export const appStore = {
  ready: false,
  expired: false,
  bootError: null,
  route: { name: 'home', params: {} },

  connections: [],
  connId: null,
  workspaces: [],
  wsLoading: false,
  wsError: null,

  tree: null,
  treeWs: null,
  treeLoading: false,
  treeError: null,
  itemIndex: {},

  theme: 'system',
  wide: false,
  drawer: false,
  expanded: {},
  recents: [],
  toasts: [],
  helpOpen: false,
  paletteOpen: false,
  modal: null,

  // ---- ciclo de vida ----
  async init() {
    this.theme = THEMES.includes(lsGet('kos.theme')) ? lsGet('kos.theme') : 'system';
    this.wide = lsGet('kos.wide') === '1';
    this.expanded = readJson('kos.expanded', {});
    this.recents = readJson('kos.recents', []);
    applyTheme(this.theme);
    setOnExpired(() => {
      this.expired = true;
    });
    window.addEventListener('hashchange', () => this.onRoute());
    await this.boot();
  },

  async boot() {
    this.ready = false;
    this.bootError = null;
    try {
      await this.loadConnections();
      await this.onRoute();
    } catch (e) {
      if (!this.expired) this.bootError = e.message;
    }
    this.ready = true;
  },

  async loadConnections() {
    let list = [];
    try {
      list = (await api('GET', '/connections')).map(normalizeConnection);
    } catch (e) {
      if (e.status === 401) throw e;
      list = [];
    }
    if (!list.length) list = [{ id: 'default', name: 'default', enabled: true, is_default: true }];
    if (!list.some((c) => c.is_default)) {
      const d = list.find((c) => c.id === 'default') || list[0];
      d.is_default = true;
    }
    this.connections = list;
  },

  // ---- rota ----
  async onRoute() {
    const r = parseHash();
    this.route = r;
    this.drawer = false;
    if (r.name === 'home') {
      const saved = lsGet('kos.conn');
      const conn =
        this.connections.find((c) => c.id === saved && c.enabled) ||
        this.connections.find((c) => c.is_default) ||
        this.connections[0];
      go(hrefs.conn(conn.id));
      return;
    }
    const conn = r.params.conn;
    if (conn && conn !== this.connId) await this.selectConnection(conn);
    if (r.params.ws && r.params.ws !== this.treeWs && this.workspaces.length) {
      await this.loadTree(r.params.ws);
    }
    this.updateTitle();
  },

  updateTitle() {
    const p = this.route.params;
    let t = 'Knowledge OS';
    if (this.route.name === 'item' && this.itemIndex[p.item]) t = this.itemIndex[p.item].title + ' · ' + t;
    else if (this.route.name === 'domain' && this.domain) t = this.domain.name + ' · ' + t;
    else if (this.route.name === 'workspace' && this.workspace) t = this.workspace.name + ' · ' + t;
    else if (this.route.name === 'connections') t = 'Conexões · ' + t;
    document.title = t;
  },

  async selectConnection(id) {
    this.connId = id;
    setConnection(id);
    lsSet('kos.conn', id);
    this.tree = null;
    this.treeWs = null;
    this.itemIndex = {};
    await this.loadWorkspaces();
  },

  async loadWorkspaces() {
    this.wsLoading = true;
    this.wsError = null;
    try {
      this.workspaces = await api('GET', '/workspaces');
      const stats = await Promise.allSettled(
        this.workspaces.map((w) => api('GET', `/workspaces/${w.id}/stats`)),
      );
      this.workspaces = this.workspaces.map((w, i) => ({
        ...w,
        stats: stats[i].status === 'fulfilled' ? stats[i].value : null,
      }));
    } catch (e) {
      this.workspaces = [];
      if (e.status !== 401) this.wsError = e.message;
    } finally {
      this.wsLoading = false;
    }
  },

  async loadTree(wsId = this.route.params.ws) {
    if (!wsId) return;
    this.treeLoading = true;
    this.treeError = null;
    this.treeWs = wsId;
    try {
      const data = await api('GET', `/workspaces/${wsId}/tree`);
      if (this.treeWs !== wsId) return;
      const index = {};
      for (const d of data.domains) {
        for (const it of d.items) {
          index[it.id] = { ...it, domain_id: d.id, domain_name: d.name, workspace_id: wsId };
        }
      }
      this.tree = data;
      this.itemIndex = index;
      const dm = this.route.params.dm;
      if (dm && this.expanded[dm] === undefined) this.expanded[dm] = true;
    } catch (e) {
      if (this.treeWs === wsId) {
        this.tree = null;
        if (e.status !== 401) this.treeError = e.message;
      }
    } finally {
      if (this.treeWs === wsId) this.treeLoading = false;
    }
  },

  async refresh() {
    await this.loadWorkspaces();
    if (this.treeWs) await this.loadTree(this.treeWs);
    this.updateTitle();
  },

  // ---- derivados ----
  get workspace() {
    return this.workspaces.find((w) => w.id === this.route.params.ws) || null;
  },
  get domain() {
    return this.tree?.domains.find((d) => d.id === this.route.params.dm) || null;
  },
  get connName() {
    return this.connections.find((c) => c.id === this.connId)?.name || this.connId || '—';
  },
  get currentItem() {
    return this.itemIndex[this.route.params.item] || null;
  },

  // ---- hrefs (usam a conexão e o workspace atuais) ----
  hConn() {
    return hrefs.conn(this.connId);
  },
  hWs(wsId) {
    return hrefs.ws(this.connId, wsId ?? this.route.params.ws);
  },
  hDomain(dmId) {
    return hrefs.domain(this.connId, this.route.params.ws, dmId);
  },
  hItem(dmId, itemId) {
    return hrefs.item(this.connId, this.route.params.ws, dmId, itemId);
  },
  hItemById(itemId) {
    const it = this.itemIndex[itemId];
    return it ? hrefs.item(this.connId, this.route.params.ws, it.domain_id, itemId) : null;
  },
  hConnections: (sub) => hrefs.connections(sub),

  // ---- árvore ----
  isOpen(dmId) {
    return this.expanded[dmId] ?? this.route.params.dm === dmId;
  },
  toggleDomain(dmId) {
    this.expanded[dmId] = !this.isOpen(dmId);
    lsSet('kos.expanded', JSON.stringify(this.expanded));
  },

  // ---- navegação ----
  pickConnection(id) {
    go(hrefs.conn(id));
  },
  pickWorkspace(id) {
    go(hrefs.ws(this.connId, id));
  },

  // ---- UI ----
  setTheme(theme) {
    this.theme = theme;
    lsSet('kos.theme', theme);
    applyTheme(theme);
  },
  cycleTheme() {
    this.setTheme(THEMES[(THEMES.indexOf(this.theme) + 1) % THEMES.length]);
  },
  toggleWide() {
    this.wide = !this.wide;
    lsSet('kos.wide', this.wide ? '1' : '0');
  },
  toast(message, kind = 'info') {
    const id = Date.now() + Math.random();
    this.toasts.push({ id, message, kind });
    setTimeout(() => {
      this.toasts = this.toasts.filter((t) => t.id !== id);
    }, 3800);
  },
};
