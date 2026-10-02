// Ponto de entrada: Alpine + store + views. Sem build step (ES modules + import map).
import Alpine from 'alpinejs';
import { captureTokenFromUrl } from './api.js';
import { appStore } from './store.js';
import { typeIcon, timeAgo, confidenceLevel } from './util.js';
import { register as registerSidebar } from './views/sidebar.js';
import { register as registerWorkspace } from './views/workspace.js';
import { register as registerDomain } from './views/domain.js';
import { register as registerItem } from './views/item.js';

// O token chega em #token=...: guarda e tira da barra de endereço antes de tudo.
captureTokenFromUrl();

window.Alpine = Alpine;
Alpine.magic('icon', () => typeIcon);
Alpine.magic('ago', () => timeAgo);
Alpine.magic('conf', () => confidenceLevel);

registerSidebar(Alpine);
registerWorkspace(Alpine);
registerDomain(Alpine);
registerItem(Alpine);

Alpine.store('app', appStore);
Alpine.start();
