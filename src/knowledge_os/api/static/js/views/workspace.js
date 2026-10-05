// Página de Workspace: domains, itens recentes e todos os itens agrupados por tipo.
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
        previewItems(d) {
          return d.items.slice(0, 3);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
