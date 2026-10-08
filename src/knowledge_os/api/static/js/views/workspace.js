// Página de Workspace: todos os itens, filtráveis por project/assunto/tipo/subtipo e buscáveis,
// e o scope do workspace (herdado por tudo o que não define o seu).
import { api } from '../api.js';
import { hrefs } from '../router.js';
import { SCOPES, inheritedNote } from '../util.js';
import { listingMixin, mix } from './listing.js';

export function register(Alpine) {
  Alpine.data('workspaceView', () =>
    mix(
      {
        scopes: SCOPES,
        scope() {
          return { workspace_id: this.app.route.params.ws };
        },
        init() {
          this.$watch(
            () => this.app.route.params.ws + '|' + this.app.treeVersion,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Link para a tela de grafo deste workspace. */
        graphHref() {
          return hrefs.graph(this.app.connId, this.app.route.params.ws);
        },
        /** Workspace é o topo da cadeia: sem explícito vale o padrão (scoped), nunca herda —
         * o seletor mostra o efetivo e não tem linha de ajuda. */
        get scopeInfo() {
          const w = this.app.workspace;
          return { value: w?.scope || 'scoped', note: inheritedNote(w?.scope_explicit, null) };
        },
        /** `scoped` grava `""` (tira o explícito: o padrão já é scoped); muda o alcance de tudo
         * o que herda. */
        async setScope(value) {
          try {
            const scope = value === 'scoped' ? '' : value;
            await api('PUT', `/workspaces/${this.app.route.params.ws}`, { body: { scope } });
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
