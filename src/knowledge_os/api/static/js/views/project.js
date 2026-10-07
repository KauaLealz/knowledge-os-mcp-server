// Página de Project: itens do project agrupados por tipo, com filtros e busca.
import { hrefs } from '../router.js';
import { listingMixin, mix } from './listing.js';

export function register(Alpine) {
  Alpine.data('projectView', () =>
    mix(
      {
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
      },
      listingMixin(Alpine),
    ),
  );
}
