// Subject page: a subject's items, with filters and search (same listing mixin as
// Workspace/Project). v6 has no scope.
import { hrefs } from '../router.js';
import { listingMixin, mix } from './listing.js';

export function register(Alpine) {
  Alpine.data('subjectView', () =>
    mix(
      {
        scope() {
          const p = this.app.route.params;
          return { workspace_id: p.ws, project_id: p.pj, subject_id: p.subj };
        },
        init() {
          this.$watch(
            () => this.app.route.params.subj + '|' + this.app.treeVersion,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Link to this subject's graph screen. */
        graphHref() {
          const p = this.app.route.params;
          return hrefs.subjectGraph(this.app.connId, p.ws, p.pj, p.subj);
        },
        /** Up one level: to the subject's project. */
        backHref() {
          const p = this.app.route.params;
          return hrefs.project(this.app.connId, p.ws, p.pj);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
