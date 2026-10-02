// Atalhos globais. Teclas de uma letra não disparam enquanto o foco está num campo de texto.

export function isTyping(target) {
  if (!target || !target.tagName) return false;
  const tag = target.tagName;
  return tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || target.isContentEditable;
}

export const isMac = /Mac|iPhone|iPad/.test(navigator.platform || '');

/** Lista exibida na ajuda (`?`). */
export const SHORTCUTS = [
  { keys: [isMac ? '⌘ K' : 'Ctrl K', '/'], label: 'Abrir a busca e os comandos' },
  { keys: ['?'], label: 'Mostrar esta ajuda' },
  { keys: ['Esc'], label: 'Fechar painel, paleta ou modal' },
  { keys: ['↑', '↓', 'Enter'], label: 'Navegar e escolher na paleta' },
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

    if (e.key === 'Escape') {
      if (app.paletteOpen) app.paletteOpen = false;
      else if (app.helpOpen) app.helpOpen = false;
      else if (app.modal) app.modal = null;
      else if (app.drawer) app.drawer = false;
      return;
    }

    if (mod || e.altKey || isTyping(e.target) || app.paletteOpen) return;

    if (e.key === '?') {
      e.preventDefault();
      app.helpOpen = !app.helpOpen;
    } else if (e.key === '/') {
      e.preventDefault();
      app.paletteOpen = true;
    }
  });
}
