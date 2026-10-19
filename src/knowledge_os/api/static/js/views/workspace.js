// Workspace page: all items, filterable by project/subject/type/tag and searchable. v6 has no
// scope — reach is by hierarchy, so the page just lists and filters.
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
        /** Link to this workspace's graph screen. */
        graphHref() {
          return hrefs.graph(this.app.connId, this.app.route.params.ws);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
