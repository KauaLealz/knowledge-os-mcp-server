// Página de Workspace: todos os itens, filtráveis por project/assunto/tipo e buscáveis.
import { hrefs } from '../router.js';
import { listingMixin, mix } from './listing.js';

export function register(Alpine) {
  Alpine.data('workspaceView', () =>
    mix(
      {
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
      },
      listingMixin(Alpine),
    ),
  );
}
