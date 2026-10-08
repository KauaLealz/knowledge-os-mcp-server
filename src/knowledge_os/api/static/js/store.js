// Store global (Alpine.store('app')): conexão, workspaces, árvore, tags, rota, tema e toasts.
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
    path: c.path ?? null,
    path_exists: !!c.path_exists,
    is_git_repo: !!c.is_git_repo,
    remote_url: c.remote_url ?? null,
    review_mode: c.review_mode || 'direct',
    enabled: c.enabled ?? c.is_active ?? true,
    is_default: !!c.is_default,
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
  // projectIds/subjectIds filtram no servidor (não só a página carregada, como types) —
  // só aparecem na UI de quem tem a árvore pra oferecer as opções (workspace e project).
  filters: { q: '', types: [], subtypes: [], projectIds: [], subjectIds: [] },
  filtersWs: null,

  // Tags gerenciadas da conexão: [{ name, count }] (count 0 = só no vocabulário).
  tags: [],
  tagsLoading: false,
  tagsError: null,

  trees: {}, // cache por workspace: { [wsId]: treeData }
  treeWs: null, // último workspace carregado (só informativo — não serve de gatilho de $watch,
  // várias gavetas podem carregar "por último" fora de ordem quando refresh() recarrega
  // todas de uma vez; use treeVersion pra isso)
  treeVersion: 0, // incrementa a cada loadTree — gatilho de $watch de workspace/project/subject.js
  treeLoadingWs: {},
  treeErrorWs: {},
  itemIndex: {},

  theme: 'light', // sempre 'light' ou 'dark' (o do sistema até o primeiro clique)
  themeChosen: false,
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
    this.expanded = readJson('kos.expanded', {});
    this.recents = readJson('kos.recents', []);
    this.lastHash = location.hash;
    window.addEventListener('hashchange', () => {
      // Edição com alterações não salvas: confirma antes de sair da rota.
      if (this.dirty && location.hash !== this.lastHash && !window.confirm('There are unsaved changes. Discard them?')) {
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
    // Sem conexão cadastrada a lista fica vazia: nada é inventado (cria-se pelo MCP, connection_create).
    if (list.length && !list.some((c) => c.is_default)) list[0].is_default = true;
    this.connections = list;
  },

  // ---- rota ----
  async onRoute() {
    const r = parseHash();
    this.route = r;
    this.drawer = false;
    if (r.name === 'home') {
      if (!this.connections.length) return; // sem conexão: a tela inicial explica como criar
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
      this.filters = { q: '', types: [], subtypes: [], projectIds: [], subjectIds: [] };
    }
    if (r.params.ws && !this.trees[r.params.ws] && this.workspaces.length) {
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
    else if (this.route.name === 'connections') t = 'Connections · ' + t;
    else if (this.route.name === 'tags') t = 'Tags · ' + t;
    document.title = t;
  },

  async selectConnection(id) {
    this.connId = id;
    setConnection(id);
    lsSet('kos.conn', id);
    this.trees = {};
    this.treeWs = null;
    this.treeLoadingWs = {};
    this.treeErrorWs = {};
    this.itemIndex = {};
    this.tags = [];
    await this.loadWorkspaces();
  },

  /** Tags com contagem (`GET /tags`): a tela de tags e as sugestões do editor usam. */
  async loadTags() {
    this.tagsLoading = true;
    this.tagsError = null;
    try {
      this.tags = await api('GET', '/tags');
    } catch (e) {
      this.tagsError = e.message;
    } finally {
      this.tagsLoading = false;
    }
  },

  async loadWorkspaces() {
    const seq = ++this.wsSeq; // resposta de chamada antiga (outra conexão) é descartada
    this.wsLoading = true;
    this.wsError = null;
    try {
      // As linhas já trazem scope (efetivo e explícito) e as contagens (projects, items).
      const list = await api('GET', '/workspaces');
      if (seq !== this.wsSeq) return;
      this.workspaces = list.map((w) => ({ ...w, stats: { projects: w.projects, items: w.items } }));
    } catch (e) {
      if (seq !== this.wsSeq) return;
      this.workspaces = [];
      this.wsError = e.message;
    } finally {
      if (seq === this.wsSeq) this.wsLoading = false;
    }
  },

  /** Carrega (ou recarrega, se chamado via refresh) a árvore de um workspace. Várias gavetas podem estar abertas ao mesmo tempo, cada uma com seu próprio cache. */
  async loadTree(wsId = this.route.params.ws) {
    if (!wsId) return;
    this.treeLoadingWs[wsId] = true;
    this.treeErrorWs[wsId] = null;
    this.treeWs = wsId;
    try {
      const data = await api('GET', `/workspaces/${wsId}/tree`);
      const index = {};
      for (const p of data.projects || []) {
        for (const it of p.items) {
          index[it.id] = { ...it, project_id: p.id, project_name: p.name, workspace_id: wsId };
        }
        for (const s of p.subjects || []) {
          for (const it of s.items) {
            index[it.id] = { ...it, project_id: p.id, project_name: p.name, workspace_id: wsId, subject_id: s.id };
          }
        }
      }
      this.trees = { ...this.trees, [wsId]: data };
      this.itemIndex = { ...this.itemIndex, ...index };
      this.treeVersion++;
      const pj = this.route.params.pj;
      if (pj && this.expanded[pj] === undefined) this.expanded[pj] = true;
    } catch (e) {
      delete this.trees[wsId];
      this.treeErrorWs[wsId] = e.message;
    } finally {
      this.treeLoadingWs[wsId] = false;
    }
  },

  async refresh() {
    await this.loadWorkspaces();
    // Recarrega todas as gavetas de workspace abertas (mínimo: a do workspace da rota atual).
    const openWs = Object.keys(this.expanded)
      .filter((k) => k.startsWith('ws:') && this.expanded[k])
      .map((k) => k.slice(3));
    const toReload = new Set(openWs);
    if (this.route.params.ws) toReload.add(this.route.params.ws);
    await Promise.all([...toReload].map((wsId) => this.loadTree(wsId)));
    this.updateTitle();
  },

  // ---- derivados ----
  get workspace() {
    return this.workspaces.find((w) => w.id === this.route.params.ws) || null;
  },
  /** Compatibilidade: árvore do workspace da rota atual (workspace.js/project.js/item.js/editor.js usam assim). */
  get tree() {
    return this.trees[this.route.params.ws] || null;
  },
  get treeLoading() {
    return !!this.treeLoadingWs[this.route.params.ws];
  },
  get treeError() {
    return this.treeErrorWs[this.route.params.ws] || null;
  },
  get project() {
    return this.tree?.projects?.find((p) => p.id === this.route.params.pj) || null;
  },
  get subject() {
    return this.project?.subjects?.find((s) => s.id === this.route.params.subj) || null;
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
  hSubject(subjId) {
    return hrefs.subject(this.connId, this.route.params.ws, this.route.params.pj, subjId);
  },
  /** Variantes com workspace/project explícitos — a sidebar lista gavetas de workspaces que
   * não são o da rota atual, então não pode usar route.params.ws/pj como os de cima. */
  hProjectIn(wsId, pjId) {
    return hrefs.project(this.connId, wsId, pjId);
  },
  hSubjectIn(wsId, pjId, subjId) {
    return hrefs.subject(this.connId, wsId, pjId, subjId);
  },
  hItemIn(wsId, pjId, itemId) {
    return hrefs.item(this.connId, wsId, pjId, itemId);
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
  hTags() {
    return hrefs.tags(this.connId);
  },

  // ---- árvore ----
  isOpen(pjId) {
    return this.expanded[pjId] ?? this.route.params.pj === pjId;
  },
  toggleProject(pjId) {
    this.expanded[pjId] = !this.isOpen(pjId);
    lsSet('kos.expanded', JSON.stringify(this.expanded));
  },
  isWorkspaceOpen(wsId) {
    return this.expanded['ws:' + wsId] ?? this.route.params.ws === wsId;
  },
  toggleWorkspace(wsId) {
    const next = !this.isWorkspaceOpen(wsId);
    this.expanded['ws:' + wsId] = next;
    lsSet('kos.expanded', JSON.stringify(this.expanded));
    if (next && !this.trees[wsId]) this.loadTree(wsId);
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
    if (this.modalGuard?.() && !window.confirm('Discard what you typed?')) return;
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
    return this.theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme';
  },
  toast(message, kind = 'info') {
    const id = Date.now() + Math.random();
    this.toasts.push({ id, message, kind });
    setTimeout(() => {
      this.toasts = this.toasts.filter((t) => t.id !== id);
    }, 3800);
  },
};
