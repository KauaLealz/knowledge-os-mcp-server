// Página de Subject: itens de um assunto, com filtros e busca (mesmo mixin de listagem de
// Workspace/Project), e o scope do assunto (herdado do project ou do workspace).
import { api } from '../api.js';
import { hrefs } from '../router.js';
import { SCOPES, inheritedNote } from '../util.js';
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
        /** Scope efetivo desta página: um scope herdado igual a ele não repete badge nas linhas. */
        get contextScope() {
          return this.app.subject?.scope || null;
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
        /** O seletor: explícito (ou `""` = herda), o efetivo e, só quando herdado, de onde vem
         * (project, depois workspace). */
        get scopeInfo() {
          const sj = this.app.subject;
          if (!sj) return { value: '', effective: 'scoped', note: '' };
          let from = null;
          if (this.app.project?.scope_explicit) from = 'project';
          else if (this.app.workspace?.scope_explicit) from = 'workspace';
          return { value: sj.scope_explicit || '', effective: sj.scope, note: inheritedNote(sj.scope_explicit, from) };
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
