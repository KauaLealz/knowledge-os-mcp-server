// Edição inline do item (textarea mono + preview) e modais Novo item / workspace / domain.
import { api } from '../api.js';
import { go, hrefs } from '../router.js';
import { renderTo } from '../markdown.js';
import { ITEM_TYPES } from '../util.js';

const EDITABLE = ['title', 'type', 'summary', 'content', 'tags'];

const splitTags = (t) => String(t).split(',').map((x) => x.trim()).filter(Boolean);

function pick(item) {
  const out = {};
  for (const k of EDITABLE) out[k] = item[k] ?? '';
  out.tags = (item.tags || []).join(', ');
  return out;
}

const blank = (v) => v === '' || v === null || v === undefined;

/** Campos que mudaram (título, resumo e conteúdo em branco não contam). Tags viram lista. */
function changes(draft, saved) {
  const out = {};
  for (const k of EDITABLE) {
    if (k === 'tags') {
      if (draft.tags !== saved.tags) out.tags = splitTags(draft.tags);
      continue;
    }
    if (blank(draft[k])) continue;
    if (draft[k] !== saved[k]) out[k] = draft[k];
  }
  return out;
}

export function register(Alpine) {
  Alpine.data('itemEditor', (item, applyUpdate) => {
    let beforeUnload = null; // fora do estado reativo
    return {
      // Segredo só nasce pelo agente; ao editar um, o tipo dele continua na lista.
      types: item.type === 'secret' ? ['secret', ...ITEM_TYPES] : ITEM_TYPES,
      draft: pick(item),
      saved: pick(item),
      saving: false,
      error: null,

      get app() {
        return Alpine.store('app');
      },
      get dirty() {
        return Object.keys(changes(this.draft, this.saved)).length > 0;
      },

      init() {
        this.app.saveHook = () => this.save();
        this.$watch(
          () => this.dirty,
          (v) => {
            this.app.dirty = v;
          },
        );
        beforeUnload = (e) => {
          if (this.dirty) {
            e.preventDefault();
            e.returnValue = '';
          }
        };
        window.addEventListener('beforeunload', beforeUnload);
        this.$nextTick(() => this.$refs.content?.focus());
      },
      destroy() {
        window.removeEventListener('beforeunload', beforeUnload);
        this.app.dirty = false;
        this.app.saveHook = null;
      },

      preview(el) {
        renderTo(el, this.draft.content);
      },

      async save() {
        if (this.saving) return;
        if (!this.dirty) {
          this.app.toast('Nada para salvar');
          return;
        }
        if (blank(this.draft.title) || blank(this.draft.summary) || blank(this.draft.content)) {
          this.error = 'Título, resumo e conteúdo não podem ficar vazios.';
          return;
        }
        this.saving = true;
        this.error = null;
        try {
          const updated = await api('PUT', `/items/${item.id}`, { body: changes(this.draft, this.saved) });
          this.saved = pick(updated);
          applyUpdate(updated);
          this.app.toast('Alterações salvas');
          this.app.loadTree(); // atualiza updated_at na árvore
        } catch (e) {
          this.error = e.message;
        } finally {
          this.saving = false;
        }
      },
    };
  });

  Alpine.data('newModal', () => ({
    types: ITEM_TYPES,
    form: {},
    initial: '',
    saving: false,
    error: null,

    get app() {
      return Alpine.store('app');
    },
    get kind() {
      return this.app.modal;
    },
    get domains() {
      return this.app.tree?.domains || [];
    },
    get title() {
      return { item: 'Novo item', workspace: 'Novo workspace', domain: 'Novo domain' }[this.kind] || '';
    },

    init() {
      const p = this.app.route.params;
      this.form = {
        name: '',
        description: '',
        workspace_id: p.ws || this.app.workspaces[0]?.id || '',
        domain_id: p.dm || this.domains[0]?.id || '',
        type: 'knowledge',
        title: '',
        summary: '',
        content: '',
        tags: '',
      };
      this.initial = JSON.stringify(this.form);
      this.app.modalGuard = () => JSON.stringify(this.form) !== this.initial;
      this.$nextTick(() => this.$refs.first?.focus());
    },

    destroy() {
      this.app.modalGuard = null;
    },

    close() {
      this.app.closeModal();
    },

    async submit() {
      if (this.saving) return;
      this.error = null;
      this.saving = true;
      try {
        if (this.kind === 'workspace') await this.createWorkspace();
        else if (this.kind === 'domain') await this.createDomain();
        else await this.createItem();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.saving = false;
      }
    },

    async createWorkspace() {
      const f = this.form;
      if (!f.name.trim()) throw new Error('Informe o nome do workspace.');
      const ws = await api('POST', '/workspaces', {
        body: { name: f.name.trim(), description: f.description.trim() || null },
      });
      await this.app.loadWorkspaces();
      this.app.modal = null;
      this.app.toast('Workspace criado');
      go(hrefs.ws(this.app.connId, ws.id));
    },

    async createDomain() {
      const f = this.form;
      if (!f.workspace_id) throw new Error('Escolha o workspace.');
      if (!f.name.trim()) throw new Error('Informe o nome do domain.');
      const dm = await api('POST', '/domains', {
        body: { workspace_id: f.workspace_id, name: f.name.trim(), description: f.description.trim() || null },
      });
      await this.app.loadTree(f.workspace_id);
      this.app.expanded[dm.id] = true;
      this.app.modal = null;
      this.app.toast('Domain criado');
      go(hrefs.domain(this.app.connId, f.workspace_id, dm.id));
    },

    async createItem() {
      const f = this.form;
      const ws = this.app.route.params.ws;
      if (!ws) throw new Error('Abra um workspace antes de criar um item.');
      if (!f.domain_id) throw new Error('Escolha o domain (crie um se ainda não houver).');
      for (const [k, label] of [['title', 'título'], ['summary', 'resumo'], ['content', 'conteúdo']]) {
        if (!String(f[k]).trim()) throw new Error(`Informe o ${label}.`);
      }
      const body = {
        workspace_id: ws,
        domain_id: f.domain_id,
        type: f.type,
        memory_class: 'longterm', // a UI não expõe classe de memória: itens novos nascem duradouros
        title: f.title.trim(),
        summary: f.summary.trim(),
        content: f.content,
        tags: splitTags(f.tags),
      };
      const it = await api('POST', '/items', { body });
      await this.app.loadTree(ws);
      this.app.modal = null;
      this.app.toast('Item criado');
      go(hrefs.item(this.app.connId, ws, it.domain_id, it.id));
    },
  }));
}
