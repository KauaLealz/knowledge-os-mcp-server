// Página de Subject: itens de um assunto, agrupados por tipo, com filtros e busca (mesmo
// mixin de listagem de Workspace/Project).
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
            () => this.app.route.params.subj + '|' + this.app.treeWs,
            () => this.loadItems(),
          );
          this.loadItems();
          this.initListing();
        },
        /** Link para a tela de grafo deste assunto. */
        graphHref() {
          const p = this.app.route.params;
          return hrefs.subjectGraph(this.app.connId, p.ws, p.pj, p.subj);
        },
      },
      listingMixin(Alpine),
    ),
  );
}
