// Página de Workspace (cards de domains + itens recentes) e lista de workspaces da conexão.
import { parseDate } from '../util.js';

export function register(Alpine) {
  Alpine.data('workspaceView', () => ({
    get app() {
      return Alpine.store('app');
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
  }));
}
