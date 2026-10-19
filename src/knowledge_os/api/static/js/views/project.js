// Project page: the project's items, with filters and search. v6 has no scope.
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
        /** Link to this project's graph screen. */
        graphHref() {
          const p = this.app.route.params;
          return hrefs.projectGraph(this.app.connId, p.ws, p.pj);
        },
        /** Up one level: to the workspace. */
        backHref() {
          return hrefs.ws(this.app.connId, this.app.route.params.ws);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
