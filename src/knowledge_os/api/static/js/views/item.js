// Página de item em modo leitura: tipo · subtipo, ⚠ revisão, scope (com o herdado indicado),
// origem, links, Markdown, TOC, relações (do grafo do item, formato `item_graph`), prev/next.
import { api } from '../api.js';
import { renderTo } from '../markdown.js';
import { go, hrefs } from '../router.js';
import { formatDate } from '../util.js';

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  return new Promise((resolve, reject) => {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try {
      document.execCommand('copy') ? resolve() : reject(new Error('copy'));
    } catch (e) {
      reject(e);
    } finally {
      ta.remove();
    }
  });
}


export function register(Alpine) {
  // Valor de segredo: só escrito (PUT) ou apagado (DELETE); a API nunca o devolve.
  Alpine.data('secretForm', (item, onUpdate) => ({
    value: '',
    multiline: false,
    busy: false,
    confirming: false,
    error: null,

    get app() {
      return Alpine.store('app');
    },
    async save() {
      if (!this.value || this.busy) return;
      this.busy = true;
      this.error = null;
      try {
        await api('PUT', `/items/${item.id}/secret`, { body: { value: this.value } });
        onUpdate(await api('GET', `/items/${item.id}`));
        this.app.toast('Value saved');
      } catch (e) {
        this.error = e.message;
      } finally {
        this.value = ''; // não fica no estado da página, nem quando a gravação falha
        this.busy = false;
      }
    },
    async clear() {
      if (!this.confirming) {
        this.confirming = true;
        return;
      }
      this.confirming = false;
      this.busy = true;
      this.error = null;
      try {
        await api('DELETE', `/items/${item.id}/secret`);
        onUpdate(await api('GET', `/items/${item.id}`));
        this.app.toast('Value deleted');
      } catch (e) {
        this.error = e.message;
      } finally {
        this.busy = false;
      }
    },
  }));

  Alpine.data('itemView', () => {
  let observer = null; // fora do estado reativo: o x-effect não pode depender dele
  return {
    item: null,
    out: [],
    inc: [],
    headings: [],
    active: '',
    loading: true,
    error: null,
    notFound: false,
    showRaw: false,
    seq: 0,
    deleting: false,
    confirmingDelete: false,

    get app() {
      return Alpine.store('app');
    },
    /** Sobe um nível: pro assunto do item (se tiver um) ou direto pro project. */
    backHref() {
      const ws = this.app.route.params.ws;
      if (!this.item) return hrefs.ws(this.app.connId, ws);
      return this.item.subject_id
        ? hrefs.subject(this.app.connId, ws, this.item.project_id, this.item.subject_id)
        : hrefs.project(this.app.connId, ws, this.item.project_id);
    },
    init() {
      this.$watch(
        () => this.app.route.params.item,
        () => this.load(),
      );
      this.load();
    },
    destroy() {
      observer?.disconnect();
    },

    async load() {
      const id = this.app.route.params.item;
      if (!id) return;
      const seq = ++this.seq;
      if (this.item && this.item.id !== id) this.item = null;
      this.loading = true;
      this.error = null;
      this.notFound = false;
      this.showRaw = false;
      this.confirmingDelete = false;
      this.headings = [];
      this.active = '';
      observer?.disconnect();
      try {
        const item = await api('GET', `/items/${id}`);
        const graph = await api('GET', `/items/${id}/graph`, { query: { depth: 1, limit: 100 } }).then(
          (value) => ({ status: 'fulfilled', value }),
          () => ({ status: 'rejected' }),
        );
        if (seq !== this.seq) return;
        this.splitRelations(item, graph.status === 'fulfilled' ? graph.value : { nodes: [], edges: [] });
        this.item = item;
        this.app.pushRecent(item);
        document.title = `${item.title} · Knowledge OS`;
        window.scrollTo(0, 0);
      } catch (e) {
        if (seq !== this.seq) return;
        this.item = null;
        if (e.status === 404) this.notFound = true;
        else this.error = e.message;
      } finally {
        if (seq === this.seq) this.loading = false;
      }
    },

    /** Grafo de 1 salto (`{nodes, edges: [{from, type, to}]}`, pontas por key ou id) em
     * "References" (saem do item) e "Referenced by" (chegam nele). */
    splitRelations(item, graph) {
      const me = item.key || item.id;
      const byRef = new Map((graph.nodes || []).map((n) => [n.key || n.id, n]));
      const out = [];
      const inc = [];
      for (const e of graph.edges || []) {
        if (e.from === me && byRef.has(e.to)) out.push({ id: `${e.type}>${e.to}`, type: e.type, node: byRef.get(e.to) });
        else if (e.to === me && byRef.has(e.from)) inc.push({ id: `${e.type}<${e.from}`, type: e.type, node: byRef.get(e.from) });
      }
      this.out = out;
      this.inc = inc;
    },

    // ---- Markdown / TOC ----
    renderInto(el, src) {
      observer?.disconnect();
      this.headings = renderTo(el, src);
      this.watchHeadings(el);
    },

    watchHeadings(el) {
      const els = [...el.querySelectorAll('h2, h3')];
      if (!els.length || typeof IntersectionObserver === 'undefined') return;
      const visible = new Set();
      observer = new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            if (e.isIntersecting) visible.add(e.target.id);
            else visible.delete(e.target.id);
          }
          const first = els.find((h) => visible.has(h.id));
          if (first) this.active = first.id;
        },
        { rootMargin: '-64px 0px -70% 0px' },
      );
      els.forEach((h) => observer.observe(h));
      this.active = els[0].id;
    },

    goTo(id) {
      const el = document.getElementById(id);
      if (!el) return;
      el.scrollIntoView({ behavior: 'smooth', block: 'start' });
      this.active = id;
    },

    /** Âncoras `#x` do conteúdo rolam até o heading em vez de mexer na rota. */
    onProseClick(e) {
      const a = e.target.closest('a[href^="#"]');
      if (!a) return;
      const href = a.getAttribute('href');
      if (href.startsWith('#/')) return;
      e.preventDefault();
      this.goTo(decodeURIComponent(href.slice(1)));
    },

    // ---- derivados ----
    get projectName() {
      return this.app.tree?.projects?.find((p) => p.id === this.item?.project_id)?.name || '';
    },
    get siblings() {
      return this.app.tree?.projects?.find((p) => p.id === this.item?.project_id)?.items || [];
    },
    get prev() {
      const i = this.siblings.findIndex((s) => s.id === this.item?.id);
      return i > 0 ? this.siblings[i - 1] : null;
    },
    get next() {
      const i = this.siblings.findIndex((s) => s.id === this.item?.id);
      return i >= 0 && i < this.siblings.length - 1 ? this.siblings[i + 1] : null;
    },
    relTitle(r) {
      return r.node.title || `${r.node.id.slice(0, 8)}…`;
    },
    /** O nó do grafo não traz o project: usa o índice da sidebar quando já carregado; senão
     * abre pelo project do item atual (relação no mesmo project é o caso comum). */
    relHref(r) {
      return this.app.hItemById(r.node.id) || hrefs.item(this.app.connId, this.app.route.params.ws, this.item.project_id, r.node.id);
    },
    fullDate: formatDate,
    /** Avisa o item no servidor (`POST /items/{id}/feedback`): `verified` grava a data. */
    async markVerified() {
      try {
        await api('POST', `/items/${this.item.id}/feedback`, { body: { outcome: 'verified' } });
        this.item = await api('GET', `/items/${this.item.id}`);
        this.app.toast('Marked as verified');
      } catch (e) {
        this.app.toast(e.message, 'error');
      }
    },

    // ---- ações ----
    applyUpdate(updated) {
      this.item = updated;
    },
    async copyMarkdown() {
      try {
        await copyText(`# ${this.item.title}\n\n${this.item.content}`);
        this.app.toast('Markdown copied');
      } catch {
        this.app.toast('Could not copy', 'error');
      }
    },
    async remove() {
      if (!this.confirmingDelete) {
        this.confirmingDelete = true;
        return;
      }
      this.deleting = true;
      this.error = null;
      const mine = this.seq; // se o usuário já navegou pra outro item, não arrasta ele de volta
      try {
        const pjId = this.item.project_id;
        const id = this.item.id;
        await api('DELETE', `/items/${id}`);
        if (mine !== this.seq) return;
        this.app.toast('Item deleted');
        go(this.app.hProject(pjId));
      } catch (e) {
        if (mine === this.seq) this.error = e.message;
      } finally {
        if (mine === this.seq) {
          this.deleting = false;
          this.confirmingDelete = false;
        }
      }
    },
  };
  });
}
