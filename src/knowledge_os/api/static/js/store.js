// Store global (Alpine.store('app')): conexão, workspaces, árvore, rota, tema e toasts.
import { api, setConnection } from './api.js';
import { parseHash, hrefs, go } from './router.js';
import { lsGet, lsSet } from './util.js';

const darkQuery = window.matchMedia ? window.matchMedia('(prefers-color-scheme: dark)') : null;
const systemTheme = () => (darkQuery && darkQuery.matches ? 'dark' : 'light');

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme === 'dark' ? 'dark' : 'light');
}

function readJson(key, fallback) {
  try {
    return JSON.parse(lsGet(key)) ?? fallback;
  } catch {
    return fallback;
  }
}

/** Tolerante a campos que a API ainda pode não ter. */
function normalizeConnection(c) {
  return {
    id: c.id,
    name: c.name || c.id,
    remote_url: c.remote_url ?? null,
    review_mode: c.review_mode || 'direct',
    enabled: c.enabled ?? c.is_active ?? true,
    is_default: !!c.is_default,
    is_catalog: !!c.is_catalog || c.id === 'default',
    last_test: c.last_test || null,
  };
}

export const appStore = {
  ready: false,
  bootError: null,
  route: { name: 'home', params: {} },

  connections: [],
  connError: null,
  connId: null,
  workspaces: [],
  wsLoading: false,
  wsSeq: 0,
  wsError: null,

  // Filtros das listas (workspace e project): ficam no store para não se perderem ao navegar.
  filters: { q: '', types: [] },
  filtersWs: null,

  tree: null,
  treeWs: null,
  treeLoading: false,
  treeError: null,
  itemIndex: {},

  theme: 'light', // sempre 'light' ou 'dark' (o do sistema até o primeiro clique)
  themeChosen: false,
  wide: false,
  drawer: false,
  expanded: {},
  recents: [],
  toasts: [],
  helpOpen: false,
  paletteOpen: false,
  modal: null,
  modalGuard: null, // devolve true quando o formulário do modal tem alterações não enviadas
  dirty: false,
  saveHook: null,
  lastHash: '',

  // ---- ciclo de vida ----
  async init() {
    const saved = lsGet('kos.theme');
    this.themeChosen = saved === 'light' || saved === 'dark';
    this.theme = this.themeChosen ? saved : systemTheme();
    if (this.themeChosen) applyTheme(this.theme);
    darkQuery?.addEventListener?.('change', () => {
      if (!this.themeChosen) this.theme = systemTheme(); // o CSS já segue o sistema
    });
    this.wide = lsGet('kos.wide') === '1';
    this.expanded = readJson('kos.expanded', {});
    this.recents = readJson('kos.recents', []);
    this.lastHash = location.hash;
    window.addEventListener('hashchange', () => {
      // Edição com alterações não salvas: confirma antes de sair da rota.
      if (this.dirty && location.hash !== this.lastHash && !window.confirm('Há alterações não salvas. Descartar?')) {
        location.hash = this.lastHash;
        return;
      }
      this.lastHash = location.hash;
      this.onRoute();
    });
    await this.boot();
  },

  async boot() {
    this.ready = false;
    this.bootError = null;
    try {
      await this.loadConnections();
      await this.onRoute();
    } catch (e) {
      this.bootError = e.message;
    }
    this.ready = true;
  },

  async loadConnections() {
    this.connError = null;
    let list;
    try {
      list = (await api('GET', '/connections')).map(normalizeConnection);
    } catch (e) {
      // Erro real: mostra (banner) e não fabrica conexão. Mantém o que já havia carregado.
      this.connError = e.message;
      return;
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
      if (!this.connections.length) return; // sem lista de conexões (erro já exibido)
      const saved = lsGet('kos.conn');
      const conn =
        this.connections.find((c) => c.id === saved && c.enabled) ||
        this.connections.find((c) => c.is_default) ||
        this.connections[0];
      go(hrefs.conn(conn.id));
      return;
    }
    if (r.name === 'connections' && !this.connId) {
      // Recarregou direto na tela de conexões: seleciona a conexão de dados (lembrada ou default).
      const saved = lsGet('kos.conn');
      const pick =
        this.connections.find((c) => c.id === saved && c.enabled) ||
        this.connections.find((c) => c.is_default) ||
        this.connections[0];
      if (pick) await this.selectConnection(pick.id);
    }
    const conn = r.params.conn;
    if (conn && conn !== this.connId) await this.selectConnection(conn);
    if (r.params.ws !== this.filtersWs) {
      this.filtersWs = r.params.ws || null;
      this.filters = { q: '', types: [] };
    }
    if (r.params.ws && r.params.ws !== this.treeWs && this.workspaces.length) {
      await this.loadTree(r.params.ws);
    }
    this.updateTitle();
  },

  updateTitle() {
    const p = this.route.params;
    let t = 'Knowledge OS';
    if (this.route.name === 'item' && this.itemIndex[p.item]) t = this.itemIndex[p.item].title + ' · ' + t;
    else if (this.route.name === 'project' && this.project) t = this.project.name + ' · ' + t;
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
    const seq = ++this.wsSeq; // resposta de chamada antiga (outra conexão) é descartada
    this.wsLoading = true;
    this.wsError = null;
    try {
      const list = await api('GET', '/workspaces');
      const stats = await Promise.allSettled(list.map((w) => api('GET', `/workspaces/${w.id}/stats`)));
      if (seq !== this.wsSeq) return;
      this.workspaces = list.map((w, i) => ({
        ...w,
        stats: stats[i].status === 'fulfilled' ? stats[i].value : null,
      }));
    } catch (e) {
      if (seq !== this.wsSeq) return;
      this.workspaces = [];
      this.wsError = e.message;
    } finally {
      if (seq === this.wsSeq) this.wsLoading = false;
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
      for (const p of data.projects || []) {
        for (const it of p.items) {
          index[it.id] = { ...it, project_id: p.id, project_name: p.name, workspace_id: wsId };
        }
      }
      this.tree = data;
      this.itemIndex = index;
      const pj = this.route.params.pj;
      if (pj && this.expanded[pj] === undefined) this.expanded[pj] = true;
    } catch (e) {
      if (this.treeWs === wsId) {
        this.tree = null;
        this.treeError = e.message;
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
  get project() {
    return this.tree?.projects?.find((p) => p.id === this.route.params.pj) || null;
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
  hProject(pjId) {
    return hrefs.project(this.connId, this.route.params.ws, pjId);
  },
  hItem(pjId, itemId) {
    return hrefs.item(this.connId, this.route.params.ws, pjId, itemId);
  },
  /** Link de um item de lista/busca (usa os ids do próprio item quando vêm). */
  hItemOf(it) {
    const ws = it.workspace_id || this.route.params.ws;
    return hrefs.item(this.connId, ws, it.project_id, it.id);
  },
  hItemById(itemId) {
    const it = this.itemIndex[itemId];
    return it ? hrefs.item(this.connId, this.route.params.ws, it.project_id, itemId) : null;
  },
  hConnections: (sub) => hrefs.connections(sub),

  // ---- árvore ----
  isOpen(pjId) {
    return this.expanded[pjId] ?? this.route.params.pj === pjId;
  },
  toggleProject(pjId) {
    this.expanded[pjId] = !this.isOpen(pjId);
    lsSet('kos.expanded', JSON.stringify(this.expanded));
  },

  // ---- navegação ----
  pickConnection(id) {
    go(hrefs.conn(id));
  },
  pickWorkspace(id) {
    go(hrefs.ws(this.connId, id));
  },

  /** Lembra os últimos itens abertos (usados pela paleta). */
  pushRecent(item) {
    const entry = {
      id: item.id,
      title: item.title,
      type: item.type,
      conn: this.connId,
      ws: item.workspace_id,
      pj: item.project_id,
    };
    this.recents = [entry, ...this.recents.filter((r) => !(r.id === entry.id && r.conn === entry.conn))].slice(0, 8);
    lsSet('kos.recents', JSON.stringify(this.recents));
  },

  // ---- edição e modais ----
  toggleEdit() {
    const p = this.route.params;
    if (this.route.name !== 'item') return;
    go(p.edit ? hrefs.item(p.conn, p.ws, p.pj, p.item) : hrefs.edit(p.conn, p.ws, p.pj, p.item));
  },
  /** Fecha o modal; se o formulário está sujo, confirma antes de descartar. */
  closeModal() {
    if (this.modalGuard?.() && !window.confirm('Descartar o que foi digitado?')) return;
    this.modalGuard = null;
    this.modal = null;
  },
  openModal(kind) {
    this.paletteOpen = false;
    this.modal = kind;
  },

  // ---- UI ----
  setTheme(theme) {
    this.theme = theme === 'dark' ? 'dark' : 'light';
    this.themeChosen = true;
    lsSet('kos.theme', this.theme);
    applyTheme(this.theme);
  },
  toggleTheme() {
    this.setTheme(this.theme === 'dark' ? 'light' : 'dark');
  },
  /** Texto da ação do botão de tema. */
  get themeAction() {
    return this.theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro';
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
