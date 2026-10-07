// Página de Workspace: projects, itens recentes e todos os itens agrupados por tipo.
import { hrefs } from '../router.js';
import { parseDate } from '../util.js';
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
            () => this.app.route.params.ws + '|' + this.app.treeWs,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Itens mais recentemente atualizados do workspace. */
        get recent() {
          const all = Object.values(this.app.itemIndex);
          return all
            .sort((a, b) => (parseDate(b.updated_at)?.getTime() || 0) - (parseDate(a.updated_at)?.getTime() || 0))
            .slice(0, 6);
        },
        get totalItems() {
          return Object.keys(this.app.itemIndex).length;
        },
        /** Link para a tela de grafo deste workspace. */
        graphHref() {
          return hrefs.graph(this.app.connId, this.app.route.params.ws);
        },
        previewItems(p) {
          return p.items.slice(0, 3);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
