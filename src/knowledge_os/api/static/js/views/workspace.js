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
            () => this.app.route.params.ws + '|' + this.app.treeVersion,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Itens deste workspace no índice global (que acumula vários workspaces ao mesmo tempo). */
        get indexed() {
          const ws = this.app.route.params.ws;
          return Object.values(this.app.itemIndex).filter((it) => it.workspace_id === ws);
        },
        /** Itens mais recentemente atualizados do workspace. */
        get recent() {
          return this.indexed
            .sort((a, b) => (parseDate(b.updated_at)?.getTime() || 0) - (parseDate(a.updated_at)?.getTime() || 0))
            .slice(0, 6);
        },
        get totalItems() {
          return this.indexed.length;
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
