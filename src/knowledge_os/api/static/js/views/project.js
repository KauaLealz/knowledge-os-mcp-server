// Página de Project: itens do project, com filtros e busca, e o scope do project (herdado do
// workspace quando não tem o seu).
import { api } from '../api.js';
import { hrefs } from '../router.js';
import { SCOPES, scopeText } from '../util.js';
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
        /** Scope efetivo; sem explícito, "inherited from workspace" quando o workspace define. */
        get scopeInfo() {
          const pj = this.app.project;
          if (!pj) return '';
          const from = !pj.scope_explicit && this.app.workspace?.scope_explicit ? 'workspace' : null;
          return scopeText(pj.scope, pj.scope_explicit, from);
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
