// Página de Project: itens do project, com filtros e busca, e o scope do project (herdado do
// workspace quando não tem o seu).
import { api } from '../api.js';
import { hrefs } from '../router.js';
import { SCOPES, inheritedNote } from '../util.js';
import { listingMixin, mix } from './listing.js';

export function register(Alpine) {
  Alpine.data('projectView', () =>
    mix(
      {
        scopes: SCOPES,
        scope() {
          const p = this.app.route.params;
          return { workspace_id: p.ws, project_id: p.pj };
        },
        init() {
          this.$watch(
            () => this.app.route.params.pj + '|' + this.app.treeVersion,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Link para a tela de grafo deste project. */
        graphHref() {
          const p = this.app.route.params;
          return hrefs.projectGraph(this.app.connId, p.ws, p.pj);
        },
        /** Sobe um nível: pro workspace. */
        backHref() {
          return hrefs.ws(this.app.connId, this.app.route.params.ws);
        },
        /** O seletor: explícito (ou `""` = herda), o efetivo e, só quando herdado de alguém,
         * "Inherited from workspace". */
        get scopeInfo() {
          const pj = this.app.project;
          if (!pj) return { value: '', effective: 'scoped', note: '' };
          const from = this.app.workspace?.scope_explicit ? 'workspace' : null;
          return { value: pj.scope_explicit || '', effective: pj.scope, note: inheritedNote(pj.scope_explicit, from) };
        },
        async setScope(value) {
          const p = this.app.route.params;
          try {
            await api('PUT', `/projects/${p.pj}`, { body: { scope: value }, query: { workspace_id: p.ws } });
            await this.app.refresh();
            this.loadItems();
            this.app.toast('Scope saved');
          } catch (e) {
            this.app.toast(e.message, 'error');
          }
        },
      },
      listingMixin(Alpine),
    ),
  );
}
