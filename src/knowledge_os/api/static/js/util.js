// Small, dependency-free utilities and the v2 taxonomy names (mirrors knowledge_os/model.py).

/** localStorage with try/catch: the page works without storage. */
export function lsGet(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function lsSet(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    /* no storage: ignore */
  }
}

/** The API returns naive UTC datetimes (utcnow): assume UTC when there's no offset. */
export function parseDate(value) {
  if (!value) return null;
  const s = String(value);
  const d = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(s) ? s : s + 'Z');
  return Number.isNaN(d.getTime()) ? null : d;
}

export function timeAgo(value) {
  const d = parseDate(value);
  if (!d) return '';
  const sec = Math.round((Date.now() - d.getTime()) / 1000);
  if (sec < 45) return 'now';
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))}m ago`;
  if (sec < 86400) return `${Math.round(sec / 3600)}h ago`;
  if (sec < 2592000) return `${Math.round(sec / 86400)}d ago`;
  if (sec < 31536000) return `${Math.round(sec / 2592000)}mo ago`;
  return `${Math.round(sec / 31536000)}y ago`;
}

export function formatDate(value) {
  const d = parseDate(value);
  return d ? d.toLocaleString('en-US', { dateStyle: 'medium', timeStyle: 'short' }) : '';
}

/**
 * Single map of item types to their display label and subtypes (all optional). No icons —
 * just a colored dot + text. Color comes from the `t-<type>` class (tokens --t-<type>).
 */
export const TYPE_META = {
  rule: { label: 'Rule', subtypes: ['code', 'pattern', 'security', 'business', 'process', 'decision'] },
  howto: { label: 'How-to', subtypes: ['procedure', 'troubleshoot'] },
  context: { label: 'Context', subtypes: ['product', 'map', 'stack', 'glossary', 'environment'] },
  spec: { label: 'Spec', subtypes: ['change', 'setup', 'dream'] },
  secret: { label: 'Secret', subtypes: [] },
};
export const TYPE_ORDER = Object.keys(TYPE_META);
/** Types the user can pick when creating an item (secret is created by the agent; the UI
 * only ever fills in its value). */
export const ITEM_TYPES = TYPE_ORDER.filter((t) => t !== 'secret');

export const SUBTYPE_LABELS = {
  code: 'Code', pattern: 'Pattern', security: 'Security', business: 'Business', process: 'Process',
  decision: 'Decision', procedure: 'Procedure', troubleshoot: 'Troubleshoot', product: 'Product',
  map: 'Map', stack: 'Stack', glossary: 'Glossary', environment: 'Environment', change: 'Change',
  setup: 'Setup', dream: 'Dream',
};

/** Status the item can be saved with: only `spec` also takes draft/done. `expired` is derived. */
export const STATUSES = ['active', 'review', 'archived'];
export const SPEC_STATUSES = ['draft', 'done'];
export function statusesFor(type) {
  return type === 'spec' ? [...STATUSES, ...SPEC_STATUSES] : STATUSES;
}

/** Where an item is valid. Without its own scope it inherits subject → project → workspace. */
export const SCOPES = ['scoped', 'workspace', 'global'];
export const SCOPE_LABELS = { scoped: 'Scoped', workspace: 'Workspace', global: 'Global' };
export const SCOPE_HINTS = {
  scoped: 'only its own project',
  workspace: 'every project of the workspace',
  global: 'everywhere',
};
/** Small icon of a non-default scope badge (sprite ids, `#i-<icon>`). */
const SCOPE_ICONS = { workspace: { icon: 'box' }, global: { icon: 'globe' } };

/** Who wrote the item: shown as a muted icon with a tooltip, never as a badge. */
export const ORIGIN_META = {
  user: { label: 'User', icon: 'user' },
  code: { label: 'Code', icon: 'code' },
  agent: { label: 'Agent', icon: 'bot' },
};

/** Lifecycle exceptions (never `active`). `review` is the only alert; the rest are neutral. */
const STATE_META = {
  review: { label: 'Review', title: 'In review: check it before trusting it' },
  draft: { label: 'Draft', title: 'Draft spec: not approved yet' },
  done: { label: 'Done', title: 'Spec delivered' },
  archived: { label: 'Archived', title: 'Archived: kept for history, not used' },
  expired: { label: 'Expired', title: 'Expired: past its time to live' },
};

export function typeLabel(type) {
  return TYPE_META[type]?.label || String(type || '');
}
/** Color class (`t-rule`...); unknown type falls back to neutral. */
export function typeClass(type) {
  return TYPE_META[type] ? 't-' + type : 't-unknown';
}
export function subtypesOf(type) {
  return TYPE_META[type]?.subtypes || [];
}
export function subtypeLabel(subtype) {
  return SUBTYPE_LABELS[subtype] || String(subtype || '');
}
/** "Rule · Decision" (or just "Rule" without a subtype). */
export function kindLabel(type, subtype) {
  return subtype ? `${typeLabel(type)} · ${subtypeLabel(subtype)}` : typeLabel(type);
}
export function scopeLabel(scope) {
  return SCOPE_LABELS[scope] || String(scope || '');
}
export function originLabel(origin) {
  return ORIGIN_META[origin]?.label || String(origin || '');
}

/** "Inherited from workspace" when the scope comes from a parent; '' when it is explicit or
 * nobody up the chain sets one (then it is the plain default and needs no note). */
export function inheritedNote(explicit, inheritedFrom) {
  return !explicit && inheritedFrom ? `Inherited from ${inheritedFrom}` : '';
}

/** Item in review: shown after the others in listings and marked ⚠ everywhere. */
export function isReview(it) {
  return it?.status === 'review';
}

/** Lifecycle state worth showing (null for `active`): review > expired > the stored status. */
export function itemState(it) {
  if (!it) return null;
  if (it.status === 'review') return 'review';
  if (it.expired) return 'expired';
  return STATE_META[it.status] ? it.status : null;
}

/** Archived and expired items are shown faded in lists and in the tree. */
export function isFaded(it) {
  const st = itemState(it);
  return st === 'archived' || st === 'expired';
}

/**
 * The scope badge, only when the effective scope is not the default `scoped`:
 * solid when set on the object itself, dashed when inherited (tooltip says from where).
 * Returns a list (0 or 1 badge) so every template renders it with the same `x-for`.
 */
export function scopeBadges(effective, explicit, inheritedFrom) {
  if (!effective || effective === 'scoped') return [];
  const inherited = !explicit && !!inheritedFrom;
  const valid = `Valid in ${SCOPE_HINTS[effective] || effective}`;
  return [{
    key: 'scope',
    cls: inherited ? 'badge scope inherited' : 'badge scope',
    icon: SCOPE_ICONS[effective]?.icon,
    label: scopeLabel(effective),
    title: inherited ? `${inheritedNote(explicit, inheritedFrom)} · ${valid}` : valid,
  }];
}

/**
 * Single source of every item badge, in a fixed order: type, state, scope.
 * Each badge is `{ key, cls, label, title, icon?, dot? }`; templates only loop over it.
 * Works with every API shape: the full item (`effective_scope` + explicit `scope` +
 * `scope_inherited_from`), a listing row, a search result or a tree/graph node (`scope` is
 * already the effective one there and where it came from is unknown: shown solid).
 * Options turn a group off: `{ type: false }`, `{ review: false }` (the item page shows the
 * review banner instead), `{ scope: false }`.
 */
export function itemBadges(it, { type = true, review = true, scope = true } = {}) {
  if (!it) return [];
  const out = [];
  if (type && it.type) {
    out.push({ key: 'type', cls: `badge type ${typeClass(it.type)}`, dot: true, label: kindLabel(it.type, it.subtype), title: 'Type' });
  }
  const st = itemState(it);
  if (st && (st !== 'review' || review)) {
    const m = STATE_META[st];
    out.push(st === 'review'
      ? { key: 'state', cls: 'badge alert', icon: 'alert', label: m.label, title: m.title }
      : { key: 'state', cls: 'badge neutral', label: m.label, title: m.title });
  }
  if (scope && 'effective_scope' in it) out.push(...scopeBadges(it.effective_scope, it.scope, it.scope_inherited_from));
  else if (scope) out.push(...scopeBadges(it.scope, it.scope, null));
  return out;
}

/**
 * Muted metadata at the end of a row (never badges): where the item lives (only where the
 * list mixes projects), who wrote it (icon + tooltip) and when it was last updated.
 * Each part is `{ key, label, title, icon? }`; with an icon, the label is for screen readers.
 */
export function itemMeta(it, { where = '' } = {}) {
  if (!it) return [];
  const out = [];
  if (where) out.push({ key: 'where', label: where, title: 'Where it lives' });
  const o = ORIGIN_META[it.origin];
  if (o) out.push({ key: 'origin', icon: o.icon, label: `Written by ${o.label.toLowerCase()}`, title: `Written by ${o.label.toLowerCase()}` });
  if (it.updated_at) out.push({ key: 'time', label: timeAgo(it.updated_at), title: `Updated ${formatDate(it.updated_at)}` });
  return out;
}

/** Badges of a connection row: only what is not the normal case (default, off, problems). */
export function connectionBadges(c, parseErrorCount = 0) {
  if (!c) return [];
  const out = [];
  if (c.is_default) out.push({ key: 'default', cls: 'badge neutral', label: 'Default', title: 'Used by MCP tools called without connection_id' });
  if (!c.enabled) out.push({ key: 'off', cls: 'badge neutral', label: 'Disabled', title: 'Disabled: not offered for reading' });
  if (!c.path_exists) out.push({ key: 'folder', cls: 'badge alert', icon: 'alert', label: 'Folder not found', title: c.path || '' });
  else if (!c.is_git_repo) out.push({ key: 'folder', cls: 'badge alert', icon: 'alert', label: 'Not a git repository', title: c.path || '' });
  if (parseErrorCount) {
    out.push({ key: 'parse', cls: 'badge alert', icon: 'alert', label: `${parseErrorCount} unreadable file${parseErrorCount === 1 ? '' : 's'}`, title: 'Files skipped when reading' });
  }
  return out;
}

/** links: one per line, "Title | https://url" (or just the url). */
export function linksToText(links) {
  return (links || []).map((l) => (l.title && l.title !== l.url ? `${l.title} | ${l.url}` : l.url)).join('\n');
}
export function textToLinks(text) {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const i = line.lastIndexOf('|');
      if (i < 0) return { url: line };
      const title = line.slice(0, i).trim();
      const url = line.slice(i + 1).trim();
      return title ? { title, url } : { url };
    });
}
