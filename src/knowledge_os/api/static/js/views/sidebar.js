// Sidebar: dropdown dos switchers (Connection / Workspace) e atalhos da árvore.

export function register(Alpine) {
  Alpine.data('dropdown', () => ({
    open: false,
    toggle() {
      this.open = !this.open;
    },
    close() {
      this.open = false;
    },
  }));
}
