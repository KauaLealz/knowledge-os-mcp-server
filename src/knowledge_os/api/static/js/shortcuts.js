// Atalhos globais. Teclas de uma letra não disparam enquanto o foco está num campo de texto.

export function isTyping(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

export const isMac = /Mac|iPhone|iPad/.test(navigator.platform || '');

/** Lista exibida na ajuda (`?`). */
export const SHORTCUTS = [
  { keys: [isMac ? '⌘ K' : 'Ctrl K', '/'], label: 'Open search and commands' },
  { keys: ['e'], label: 'Toggle between Read and Edit (on an item page)' },
  { keys: [isMac ? '⌘ S' : 'Ctrl S'], label: 'Save the edit' },
  { keys: ['?'], label: 'Show this help' },
  { keys: ['Esc'], label: 'Close panel, palette or modal' },
  { keys: ['↑', '↓', 'Enter'], label: 'Navigate and choose in the palette' },
];

export function registerShortcuts(app) {
  document.addEventListener('keydown', (e) => {
    const mod = e.ctrlKey || e.metaKey;

    if (mod && !e.altKey && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      app.helpOpen = false;
      app.paletteOpen = !app.paletteOpen;
      return;
    }

    if (mod && !e.altKey && e.key.toLowerCase() === 's' && app.route.params.edit) {
      e.preventDefault();
      app.saveHook?.();
      return;
    }

    if (e.key === 'Escape') {
      if (app.paletteOpen) app.paletteOpen = false;
      else if (app.helpOpen) app.helpOpen = false;
      else if (app.modal) app.closeModal();
      else if (app.drawer) app.drawer = false;
      else if (app.route.params.edit) app.toggleEdit();
      return;
    }

    if (mod || e.altKey || isTyping(e.target) || app.paletteOpen) return;

    if (e.key === '?') {
      e.preventDefault();
      app.helpOpen = !app.helpOpen;
    } else if (e.key === 'e' && app.route.name === 'item' && !app.modal) {
      e.preventDefault();
      app.toggleEdit();
    } else if (e.key === '/') {
      e.preventDefault();
      app.paletteOpen = true;
    }
  });
}
