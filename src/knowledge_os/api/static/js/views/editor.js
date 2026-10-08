// Edição inline do item (textarea mono + preview) e modais Novo item / workspace / project.
// Campos do v2: tipo + subtipo, scope (vazio = herda), status, links, tags e ttl_days; a
// origem (`origin`) só aparece, não se edita. Quem valida é a API (mensagem do serviço).
import { api } from '../api.js';
import { go, hrefs } from '../router.js';
import { renderTo } from '../markdown.js';
import { ITEM_TYPES, SCOPES, linksToText, statusesFor, subtypesOf, textToLinks } from '../util.js';

const EDITABLE = ['title', 'type', 'subtype', 'scope', 'status', 'summary', 'content', 'tags', 'links', 'ttl_days'];
// Podem ficar vazios: subtipo, scope e prazo vazios são "nenhum" (o scope volta a herdar).
const NULLABLE = ['subtype', 'scope', 'ttl_days'];

const splitTags = (t) => String(t).split(',').map((x) => x.trim()).filter(Boolean);

function pick(item) {
  const out = {};
  for (const k of EDITABLE) out[k] = item[k] ?? '';
  out.tags = (item.tags || []).join(', ');
  out.links = linksToText(item.links);
  out.ttl_days = item.ttl_days == null ? '' : String(item.ttl_days);
  return out;
}

const blank = (v) => v === '' || v === null || v === undefined;

/** Campos que mudaram (título, resumo e conteúdo em branco não contam). Tags e links viram
 * lista; subtipo/scope/prazo em branco viram null. */
function changes(draft, saved) {
  const out = {};
  for (const k of EDITABLE) {
    if (draft[k] === saved[k]) continue;
    if (k === 'tags') out.tags = splitTags(draft.tags);
    else if (k === 'links') out.links = textToLinks(draft.links);
    else if (k === 'ttl_days') out.ttl_days = blank(draft.ttl_days) ? null : Number(draft.ttl_days);
    else if (NULLABLE.includes(k)) out[k] = blank(draft[k]) ? null : draft[k];
    else if (!blank(draft[k])) out[k] = draft[k];
  }
  return out;
}

export function register(Alpine) {
  Alpine.data('itemEditor', (item, applyUpdate) => {
    let beforeUnload = null; // fora do estado reativo
    return {
      // Segredo só nasce pelo agente; ao editar um, o tipo dele continua na lista.
      types: item.type === 'secret' ? ['secret', ...ITEM_TYPES] : ITEM_TYPES,
      scopes: SCOPES,
      origin: item.origin,
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
      get subtypes() {
        return subtypesOf(this.draft.type);
      },
      get statuses() {
        return statusesFor(this.draft.type);
      },

      init() {
        this.app.saveHook = () => this.save();
        this.$watch(
          () => this.dirty,
          (v) => {
            this.app.dirty = v;
          },
        );
        // Trocar o tipo limpa o subtipo que não serve mais (e o status só de spec).
        this.$watch('draft.type', (t) => {
          if (this.draft.subtype && !subtypesOf(t).includes(this.draft.subtype)) this.draft.subtype = '';
          if (!statusesFor(t).includes(this.draft.status)) this.draft.status = 'active';
        });
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
          this.app.toast('Nothing to save');
          return;
        }
        if (blank(this.draft.title) || blank(this.draft.summary)) {
          this.error = 'Title and summary cannot be empty.';
          return;
        }
        this.saving = true;
        this.error = null;
        try {
          const updated = await api('PUT', `/items/${item.id}`, { body: changes(this.draft, this.saved) });
          this.saved = pick(updated);
          this.draft = pick(updated);
          applyUpdate(updated);
          this.app.toast('Changes saved');
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
    scopes: SCOPES,
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
    get projects() {
      return this.app.tree?.projects || [];
    },
    get subtypes() {
      return subtypesOf(this.form.type);
    },
    get title() {
      return { item: 'New item', workspace: 'New workspace', project: 'New project' }[this.kind] || '';
    },

    init() {
      const p = this.app.route.params;
      this.form = {
        name: '',
        description: '',
        workspace_id: p.ws || this.app.workspaces[0]?.id || '',
        project_id: p.pj || this.projects[0]?.id || '',
        type: 'rule',
        subtype: '',
        scope: '',
        title: '',
        summary: '',
        content: '',
        tags: '',
      };
      this.initial = JSON.stringify(this.form);
      this.app.modalGuard = () => JSON.stringify(this.form) !== this.initial;
      this.$watch('form.type', (t) => {
        if (this.form.subtype && !subtypesOf(t).includes(this.form.subtype)) this.form.subtype = '';
      });
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
        else if (this.kind === 'project') await this.createProject();
        else await this.createItem();
      } catch (e) {
        this.error = e.message;
      } finally {
        this.saving = false;
      }
    },

    async createWorkspace() {
      const f = this.form;
      if (!f.name.trim()) throw new Error('Enter the workspace name.');
      const ws = await api('POST', '/workspaces', {
        body: { name: f.name.trim(), description: f.description.trim() || null, scope: f.scope || null },
      });
      await this.app.loadWorkspaces();
      this.app.modal = null;
      this.app.toast('Workspace created');
      go(hrefs.ws(this.app.connId, ws.id));
    },

    async createProject() {
      const f = this.form;
      if (!f.workspace_id) throw new Error('Choose the workspace.');
      if (!f.name.trim()) throw new Error('Enter the project name.');
      const pj = await api('POST', '/projects', {
        body: {
          workspace_id: f.workspace_id,
          name: f.name.trim(),
          description: f.description.trim() || null,
          scope: f.scope || null,
        },
      });
      await this.app.loadTree(f.workspace_id);
      this.app.expanded[pj.id] = true;
      this.app.modal = null;
      this.app.toast('Project created');
      go(hrefs.project(this.app.connId, f.workspace_id, pj.id));
    },

    async createItem() {
      const f = this.form;
      const ws = this.app.route.params.ws;
      if (!ws) throw new Error('Open a workspace before creating an item.');
      if (!f.project_id) throw new Error('Choose the project (create one if there isn\'t one yet).');
      for (const [k, label] of [['title', 'title'], ['summary', 'summary']]) {
        if (!String(f[k]).trim()) throw new Error(`Enter the ${label}.`);
      }
      // Itens criados pela UI nascem com origin "user" (quem escreveu foi a pessoa).
      const body = {
        workspace_id: ws,
        project_id: f.project_id,
        type: f.type,
        subtype: f.subtype || null,
        scope: f.scope || null,
        origin: 'user',
        title: f.title.trim(),
        summary: f.summary.trim(),
        content: f.content,
        tags: splitTags(f.tags),
      };
      const it = await api('POST', '/items', { body });
      await this.app.loadTree(ws);
      this.app.modal = null;
      this.app.toast('Item created');
      go(hrefs.item(this.app.connId, ws, it.project_id, it.id));
    },
  }));
}
