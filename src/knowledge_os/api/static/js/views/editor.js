// Inline item editing (mono textarea + preview) and the New item / workspace / project modals.
// v6 fields: type, key, title, summary, content, tags, links. Nuance and lifecycle live in
// tags; there is no subtype/scope/status/ttl/origin. The API validates (service message).
import { api } from '../api.js';
import { go, hrefs } from '../router.js';
import { renderTo } from '../markdown.js';
import { ITEM_TYPES, linksToText, textToLinks } from '../util.js';

const EDITABLE = ['title', 'type', 'summary', 'content', 'tags', 'links'];

const splitTags = (t) => String(t).split(',').map((x) => x.trim()).filter(Boolean);

function pick(item) {
  const out = {};
  for (const k of EDITABLE) out[k] = item[k] ?? '';
  out.tags = (item.tags || []).join(', ');
  out.links = linksToText(item.links);
  return out;
}

const blank = (v) => v === '' || v === null || v === undefined;

/** Changed fields (empty title/summary/content do not count). Tags and links become lists. */
function changes(draft, saved) {
  const out = {};
  for (const k of EDITABLE) {
    if (draft[k] === saved[k]) continue;
    if (k === 'tags') out.tags = splitTags(draft.tags);
    else if (k === 'links') out.links = textToLinks(draft.links);
    else if (!blank(draft[k])) out[k] = draft[k];
  }
  return out;
}

export function register(Alpine) {
  Alpine.data('itemEditor', (item, applyUpdate) => {
    let beforeUnload = null; // outside reactive state
    return {
      // A secret is only born through the agent; when editing one, its type stays in the list.
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
          this.app.loadTree(); // refresh updated_at in the tree
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
    get projects() {
      return this.app.tree?.projects || [];
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
        body: { name: f.name.trim(), description: f.description.trim() || null },
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
      const body = {
        workspace_id: ws,
        project_id: f.project_id,
        type: f.type,
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
