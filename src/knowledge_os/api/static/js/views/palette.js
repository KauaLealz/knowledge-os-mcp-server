// Paleta Ctrl/Cmd+K: Recentes / Items (busca em todos os workspaces) / Projects-Workspaces / Ações / Configurações.
import { api } from '../api.js';
import { go, hrefs } from '../router.js';

const REMOTE_LIMIT = 20; // máximo de itens na paleta

const norm = (s) =>
  String(s || '')
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');

export function register(Alpine) {
  Alpine.data('palette', () => {
    // Fora do estado reativo: timers e contador de requisições.
    let timer = null;
    let seq = 0;
    return {
      q: '',
      sel: 0,
      remote: [],
      searching: false,

      get app() {
        return Alpine.store('app');
      },

      init() {
        // O overlay é um x-if: o componente nasce a cada abertura, já com o campo visível.
        this.$nextTick(() => this.$refs.input?.focus());
        this.$watch('q', () => {
          this.sel = 0;
          this.search();
        });
      },

      search() {
        clearTimeout(timer);
        const q = this.q.trim();
        if (q.length < 2) {
          this.remote = [];
          return;
        }
        timer = setTimeout(async () => {
          const mine = ++seq;
          this.searching = true;
          try {
            const res = await api('GET', '/items/search', { query: { query: q, limit: REMOTE_LIMIT } });
            if (mine === seq) this.remote = res.results;
          } catch {
            if (mine === seq) this.remote = []; // a busca remota pode falhar: a busca local segue valendo
          } finally {
            if (mine === seq) this.searching = false;
          }
        }, 160);
      },

      /** Grupos já com índice global (idx) para navegação por teclado. */
      get groups() {
        const app = this.app;
        const q = norm(this.q.trim());
        const match = (t) => !q || norm(t).includes(q);
        const groups = [];
        let idx = 0;
        const add = (label, entries) => {
          if (entries.length) groups.push({ label, entries: entries.map((e) => ({ ...e, idx: idx++ })) });
        };

        add(
          'Recent',
          app.recents
            .filter((r) => r.conn === app.connId && match(r.title))
            .slice(0, q ? 4 : 6)
            .map((r) => ({
              key: 'r' + r.id,
              title: r.title,
              sub: '',
              it: { type: r.type, subtype: r.subtype },
              hash: hrefs.item(r.conn, r.ws, r.pj, r.id),
            })),
        );

        if (q) {
          const seen = new Set();
          const items = [];
          for (const r of this.remote) {
            if (seen.has(r.id)) continue;
            seen.add(r.id);
            const hash = r.workspace_id && r.project_id ? hrefs.item(app.connId, r.workspace_id, r.project_id, r.id) : app.hItemById(r.id);
            items.push({ key: 'i' + r.id, title: r.title, sub: this.where(r), summary: r.summary, it: r, hash });
          }
          // Se a busca do servidor falhou, ainda acha pelo título nos itens do workspace aberto.
          if (!this.remote.length) {
            for (const it of Object.values(app.itemIndex)) {
              if (!match(it.title)) continue;
              items.push({ key: 'i' + it.id, title: it.title, sub: it.project_name, it, hash: app.hItemById(it.id) });
            }
          }
          add('Items', items.slice(0, REMOTE_LIMIT));
        }

        const places = [];
        for (const p of app.tree?.projects || []) {
          if (match(p.name)) {
            places.push({ key: 'p' + p.id, title: p.name, sub: `Project · ${p.item_count} items`, icon: 'folder', hash: app.hProject(p.id) });
          }
        }
        for (const w of app.workspaces) {
          if (match(w.name)) {
            places.push({ key: 'w' + w.id, title: w.name, sub: 'Workspace', icon: 'box', hash: app.hWs(w.id) });
          }
        }
        add('Projects & workspaces', places.slice(0, 8));

        add('Actions', this.actions().filter((a) => match(a.title)));

        const settings = [
          { key: 's-conn', title: 'Connections', sub: 'Settings', icon: 'db', hash: app.hConnections() },
          { key: 's-theme', title: app.themeAction, sub: 'Settings', icon: app.theme === 'dark' ? 'sun' : 'moon', run: () => app.toggleTheme() },
        ];
        add('Settings', settings.filter((s) => match(s.title)));
        return groups;
      },

      /** "Workspace › Project" de um resultado da busca (`where` = "Workspace/Project"); o ⚠
       * de revisão vem do badge de state, como nas listas. */
      where(r) {
        return String(r.where || '').split('/').filter(Boolean).join(' › ');
      },

      /** Ações da paleta. */
      actions() {
        const app = this.app;
        return [
          { key: 'a-new-item', title: 'New item', sub: 'Create in the current workspace', icon: 'plus', run: () => app.openModal('item') },
          { key: 'a-new-project', title: 'New project', sub: '', icon: 'folder', run: () => app.openModal('project') },
          { key: 'a-new-ws', title: 'New workspace', sub: '', icon: 'box', run: () => app.openModal('workspace') },
          { key: 'a-edit', title: 'Toggle Read / Edit', sub: 'e', icon: 'edit', run: () => app.toggleEdit() },
          { key: 'a-help', title: 'View keyboard shortcuts', sub: '?', icon: 'command', run: () => (app.helpOpen = true) },
          { key: 'a-refresh', title: 'Reload data', sub: '', icon: 'refresh', run: () => app.refresh() },
        ];
      },

      get flat() {
        return this.groups.flatMap((g) => g.entries);
      },

      move(n) {
        const len = this.flat.length;
        if (!len) return;
        this.sel = (this.sel + n + len) % len;
        this.$nextTick(() => document.getElementById('pal-' + this.sel)?.scrollIntoView({ block: 'nearest' }));
      },

      choose(entry) {
        if (!entry) return;
        this.app.paletteOpen = false;
        if (entry.hash) go(entry.hash);
        else entry.run?.();
      },

      chooseSelected() {
        this.choose(this.flat[this.sel]);
      },
    };
  });
}
