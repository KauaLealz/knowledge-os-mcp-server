// Página de item em modo leitura: selo de tipo, Markdown, TOC, relações, artifacts, prev/next.
import { api, download } from '../api.js';
import { renderTo } from '../markdown.js';
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

function humanSize(n) {
  if (n < 1024) return `${n} B`;
  if (n < 1048576) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1048576).toFixed(1)} MB`;
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
        this.app.toast('Valor salvo');
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
        this.app.toast('Valor apagado');
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
    artifacts: [],
    headings: [],
    active: '',
    loading: true,
    error: null,
    notFound: false,
    showRaw: false,
    seq: 0,

    get app() {
      return Alpine.store('app');
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
      this.headings = [];
      this.active = '';
      observer?.disconnect();
      try {
        const item = await api('GET', `/items/${id}`);
        const [rels, arts] = await Promise.allSettled([
          api('GET', `/items/${id}/relations`),
          api('GET', '/artifacts', { query: { item_id: id } }),
        ]);
        if (seq !== this.seq) return;
        this.splitRelations(id, rels.status === 'fulfilled' ? rels.value : {});
        this.artifacts = arts.status === 'fulfilled' ? arts.value : [];
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

    splitRelations(id, grouped) {
      const out = [];
      const inc = [];
      for (const [type, list] of Object.entries(grouped)) {
        for (const rel of list) {
          if (rel.source_item_id === id) out.push({ id: rel.id, type, other: rel.target_item_id });
          else inc.push({ id: rel.id, type, other: rel.source_item_id });
        }
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
      return this.app.tree?.projects.find((p) => p.id === this.item?.project_id)?.name || '';
    },
    get siblings() {
      return this.app.tree?.projects.find((p) => p.id === this.item?.project_id)?.items || [];
    },
    get prev() {
      const i = this.siblings.findIndex((s) => s.id === this.item?.id);
      return i > 0 ? this.siblings[i - 1] : null;
    },
    get next() {
      const i = this.siblings.findIndex((s) => s.id === this.item?.id);
      return i >= 0 && i < this.siblings.length - 1 ? this.siblings[i + 1] : null;
    },
    relTitle(id) {
      return this.app.itemIndex[id]?.title || `${id.slice(0, 8)}…`;
    },
    relHref(id) {
      return this.app.hItemById(id);
    },
    fullDate: formatDate,
    humanSize,

    // ---- ações ----
    applyUpdate(updated) {
      this.item = updated;
    },
    async copyMarkdown() {
      try {
        await copyText(`# ${this.item.title}\n\n${this.item.content}`);
        this.app.toast('Markdown copiado');
      } catch {
        this.app.toast('Não foi possível copiar', 'error');
      }
    },
    async downloadArtifact(a) {
      try {
        await download(`/artifacts/${a.id}`, a.filename);
      } catch (e) {
        this.app.toast(e.message, 'error');
      }
    },
  };
  });
}
