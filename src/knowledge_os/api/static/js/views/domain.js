// Página de Domain: itens do domain agrupados por tipo, com filtros e busca.
import { listingMixin, mix, LIMIT } from './listing.js';

export function register(Alpine) {
  Alpine.data('domainView', () =>
    mix(
      {
        scope() {
          const p = this.app.route.params;
          return { workspace_id: p.ws, domain_id: p.dm };
        },
        init() {
          this.$watch(
            () => this.app.route.params.dm + '|' + this.app.treeWs,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Lista cheia (== limite) ou menor que o item_count da árvore: avisa que há mais itens. */
        get truncated() {
          const total = this.app.domain?.item_count ?? 0;
          return !this.loading && this.items.length > 0 && (this.items.length >= LIMIT || this.items.length < total);
        },
        get totalItems() {
          return Math.max(this.app.domain?.item_count ?? 0, this.items.length);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
