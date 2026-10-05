// Ponto de entrada: Alpine + store + views. Sem build step (ES modules + import map).
import Alpine from 'alpinejs';
import { appStore } from './store.js';
import { typeIcon, timeAgo, confidenceLevel } from './util.js';
import { register as registerSidebar } from './views/sidebar.js';
import { register as registerWorkspace } from './views/workspace.js';
import { register as registerDomain } from './views/domain.js';
import { register as registerItem } from './views/item.js';
import { register as registerPalette } from './views/palette.js';
import { register as registerEditor } from './views/editor.js';
import { register as registerConnections } from './views/connections.js';
import { registerShortcuts, SHORTCUTS, isMac } from './shortcuts.js';

window.Alpine = Alpine;
Alpine.magic('icon', () => typeIcon);
Alpine.magic('ago', () => timeAgo);
Alpine.magic('conf', () => confidenceLevel);

registerSidebar(Alpine);
registerWorkspace(Alpine);
registerDomain(Alpine);
registerItem(Alpine);
registerPalette(Alpine);
registerEditor(Alpine);
registerConnections(Alpine);

appStore.shortcuts = SHORTCUTS;
appStore.isMac = isMac;
Alpine.store('app', appStore);
registerShortcuts(Alpine.store('app'));
Alpine.start();
