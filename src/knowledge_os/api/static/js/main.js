// Ponto de entrada: Alpine + store + views. Sem build step (ES modules + import map).
import Alpine from '../vendor/alpine.esm.js';
import { appStore } from './store.js';
import {
  connectionBadges, isFaded, itemBadges, itemMeta, kindLabel, typeLabel, typeClass, timeAgo,
} from './util.js';
import { register as registerSidebar } from './views/sidebar.js';
import { register as registerWorkspace } from './views/workspace.js';
import { register as registerProject } from './views/project.js';
import { register as registerSubject } from './views/subject.js';
import { register as registerItem } from './views/item.js';
import { register as registerGraph } from './views/graph.js';
import { register as registerPalette } from './views/palette.js';
import { register as registerEditor } from './views/editor.js';
import { register as registerConnections } from './views/connections.js';
import { register as registerTags } from './views/tags.js';
import { registerShortcuts, SHORTCUTS, isMac } from './shortcuts.js';

window.Alpine = Alpine;
Alpine.magic('ago', () => timeAgo);
Alpine.magic('tlabel', () => typeLabel);
Alpine.magic('tc', () => typeClass);
// v6: just the type label (nuance is a tag, shown separately).
Alpine.magic('kind', () => kindLabel);
// Single badge system (type + lifecycle tag) and the muted metadata (where, time): every
// template walks these lists with the same bit of markup.
Alpine.magic('badges', () => itemBadges);
Alpine.magic('connbadges', () => connectionBadges);
Alpine.magic('meta', () => itemMeta);
Alpine.magic('faded', () => isFaded);

registerSidebar(Alpine);
registerWorkspace(Alpine);
registerProject(Alpine);
registerSubject(Alpine);
registerItem(Alpine);
registerGraph(Alpine);
registerPalette(Alpine);
registerEditor(Alpine);
registerConnections(Alpine);
registerTags(Alpine);

appStore.shortcuts = SHORTCUTS;
appStore.isMac = isMac;
Alpine.store('app', appStore);
registerShortcuts(Alpine.store('app'));
Alpine.start();
