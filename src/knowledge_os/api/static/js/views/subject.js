// Página de Subject: itens de um assunto, com filtros e busca (mesmo mixin de listagem de
// Workspace/Project), e o scope do assunto (herdado do project ou do workspace).
import { api } from '../api.js';
import { hrefs } from '../router.js';
import { SCOPES, scopeText } from '../util.js';
import { listingMixin, mix } from './listing.js';

export function register(Alpine) {
  Alpine.data('subjectView', () =>
    mix(
      {
        scopes: SCOPES,
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
        /** Link para a tela de grafo deste assunto. */
        graphHref() {
          const p = this.app.route.params;
          return hrefs.subjectGraph(this.app.connId, p.ws, p.pj, p.subj);
        },
        /** Sobe um nível: pro project deste assunto. */
        backHref() {
          const p = this.app.route.params;
          return hrefs.project(this.app.connId, p.ws, p.pj);
        },
        /** Scope efetivo; sem explícito, de onde vem (project, depois workspace). */
        get scopeInfo() {
          const sj = this.app.subject;
          if (!sj) return '';
          let from = null;
          if (!sj.scope_explicit) {
            if (this.app.project?.scope_explicit) from = 'project';
            else if (this.app.workspace?.scope_explicit) from = 'workspace';
          }
          return scopeText(sj.scope, sj.scope_explicit, from);
        },
        async setScope(value) {
          const p = this.app.route.params;
          try {
            await api('PUT', `/subjects/${p.subj}`, {
              body: { scope: value },
              query: { workspace_id: p.ws, project_id: p.pj },
            });
            await this.app.refresh();
            this.loadItems();
            this.app.toast('Scope saved');
          } catch (e) {
            this.app.toast(e.message, 'error');
          }
        },
      },
      listingMixin(Alpine),
    ),
  );
}
