// Página de Project: itens do project agrupados por tipo, com filtros e busca.
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
            () => this.app.route.params.pj + '|' + this.app.treeWs,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        get totalItems() {
          return Math.max(this.app.project?.item_count ?? 0, this.items.length);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
