// Paleta Ctrl/Cmd+K: Recentes / Items (com summary) / Domains-Workspaces / Ações / Configurações.
import { api } from '../api.js';
import { go, hrefs } from '../router.js';
import { typeIcon } from '../util.js';

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
        const ws = this.app.route.params.ws;
        if (q.length < 2 || !ws) {
          this.remote = [];
          return;
        }
        timer = setTimeout(async () => {
          const mine = ++seq;
          this.searching = true;
          try {
            const res = await api('GET', '/items/search', { query: { query: q, workspace_id: ws, limit: 8 } });
            if (mine === seq) this.remote = res.results;
          } catch {
            if (mine === seq) this.remote = []; // FTS pode recusar a consulta: a busca local segue valendo
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
          'Recentes',
          app.recents
            .filter((r) => r.conn === app.connId && match(r.title))
            .slice(0, q ? 4 : 6)
            .map((r) => ({
              key: 'r' + r.id,
              title: r.title,
              sub: '',
              icon: typeIcon(r.type),
              hash: hrefs.item(r.conn, r.ws, r.dm, r.id),
            })),
        );

        if (q) {
          const seen = new Set();
          const items = [];
          for (const r of this.remote) {
            const it = app.itemIndex[r.id];
            if (!it || seen.has(r.id)) continue;
            seen.add(r.id);
            items.push({ key: 'i' + r.id, title: r.title, sub: r.summary, icon: typeIcon(it.type), hash: app.hItemById(r.id) });
          }
          for (const it of Object.values(app.itemIndex)) {
            if (seen.has(it.id) || !match(it.title)) continue;
            seen.add(it.id);
            items.push({ key: 'i' + it.id, title: it.title, sub: it.domain_name, icon: typeIcon(it.type), hash: app.hItemById(it.id) });
          }
          add('Items', items.slice(0, 8));
        }

        const places = [];
        for (const d of app.tree?.domains || []) {
          if (match(d.name)) {
            places.push({ key: 'd' + d.id, title: d.name, sub: `Domain · ${d.item_count} itens`, icon: 'folder', hash: app.hDomain(d.id) });
          }
        }
        for (const w of app.workspaces) {
          if (match(w.name)) {
            places.push({ key: 'w' + w.id, title: w.name, sub: 'Workspace', icon: 'box', hash: app.hWs(w.id) });
          }
        }
        add('Domains e Workspaces', places.slice(0, 8));

        add('Ações', this.actions().filter((a) => match(a.title)));

        const settings = [
          { key: 's-conn', title: 'Conexões', sub: 'Configurações', icon: 'db', hash: app.hConnections() },
          { key: 's-t-system', title: 'Tema: sistema', sub: 'Configurações', icon: 'monitor', run: () => app.setTheme('system') },
          { key: 's-t-light', title: 'Tema: claro', sub: 'Configurações', icon: 'sun', run: () => app.setTheme('light') },
          { key: 's-t-dark', title: 'Tema: escuro', sub: 'Configurações', icon: 'moon', run: () => app.setTheme('dark') },
        ];
        add('Configurações', settings.filter((s) => match(s.title)));
        return groups;
      },

      /** Ações da paleta (T7 acrescenta as de criação). */
      actions() {
        const app = this.app;
        return [
          { key: 'a-wide', title: 'Alternar largura do conteúdo', sub: '', icon: 'expand', run: () => app.toggleWide() },
          { key: 'a-help', title: 'Ver atalhos de teclado', sub: '?', icon: 'command', run: () => (app.helpOpen = true) },
          { key: 'a-refresh', title: 'Recarregar dados', sub: '', icon: 'refresh', run: () => app.refresh() },
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
