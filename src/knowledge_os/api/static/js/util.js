// Small, dependency-free utilities and the v6 taxonomy names (mirrors knowledge_os/model.py).
// v6: five item types, no subtypes. Nuance and lifecycle live in tags, not fields. There is no
// scope, status, origin or feedback. Reach is by hierarchy (where the item lives).

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
 * Single map of the five item types to their display label. No subtypes — nuance is a tag.
 * No icons: just a colored dot + text. Color comes from the `t-<type>` class (tokens --t-<type>).
 */
export const TYPE_META = {
  rule: { label: 'Rule' },
  howto: { label: 'How-to' },
  context: { label: 'Context' },
  work: { label: 'Work' },
  secret: { label: 'Secret' },
};
export const TYPE_ORDER = Object.keys(TYPE_META);
/** Types the user can pick when creating an item (secret is created by the agent; the UI
 * only ever fills in its value). */
export const ITEM_TYPES = TYPE_ORDER.filter((t) => t !== 'secret');

/** Base tag vocabulary, seeded, extensible (mirrors model.LIFECYCLE_TAGS / NUANCE_TAGS). */
export const LIFECYCLE_TAGS = ['draft', 'active', 'done', 'archived'];
export const NUANCE_TAGS = ['decision', 'troubleshoot', 'security', 'pattern', 'map',
  'glossary', 'product', 'environment', 'business', 'process'];
export const BASE_TAGS = [...LIFECYCLE_TAGS, ...NUANCE_TAGS];

/** Link relations between two items (mirrors model.LINK_RELATIONS). */
export const LINK_RELATIONS = ['depends_on', 'relates_to'];

/** Lifecycle tags worth showing as a neutral badge (never `active`, the normal case). */
const LIFECYCLE_BADGE = {
  draft: { label: 'Draft', title: 'Draft: work in progress' },
  done: { label: 'Done', title: 'Done: finished work, kept for the why' },
  archived: { label: 'Archived', title: 'Archived: kept for history, not used' },
};

export function typeLabel(type) {
  return TYPE_META[type]?.label || String(type || '');
}
/** Color class (`t-rule`...); unknown type falls back to neutral. */
export function typeClass(type) {
  return TYPE_META[type] ? 't-' + type : 't-unknown';
}
/** Just the type label in v6 (nuance is a tag, shown separately). */
export function kindLabel(type) {
  return typeLabel(type);
}

/** The lifecycle tag the item carries, if any (draft/done/archived); null otherwise. */
export function lifecycleOf(it) {
  const tags = it?.tags || [];
  return LIFECYCLE_TAGS.find((t) => t !== 'active' && tags.includes(t)) || null;
}

/** Archived items are shown faded in lists and in the tree. */
export function isFaded(it) {
  return !!it && (it.tags || []).includes('archived');
}

/**
 * Single source of every item badge, in a fixed order: type, lifecycle (tag). No scope/status.
 * Each badge is `{ key, cls, label, title, icon?, dot? }`; templates only loop over it.
 * Works with every API shape (full item, listing row, search result, tree/graph node): all carry
 * `type` and `tags`.
 * Options turn a group off: `{ type: false }`, `{ lifecycle: false }`.
 */
export function itemBadges(it, { type = true, lifecycle = true } = {}) {
  if (!it) return [];
  const out = [];
  if (type && it.type) {
    out.push({ key: 'type', cls: `badge type ${typeClass(it.type)}`, dot: true, label: kindLabel(it.type), title: 'Type' });
  }
  const life = lifecycleOf(it);
  if (lifecycle && life) {
    const m = LIFECYCLE_BADGE[life];
    out.push({ key: 'life', cls: 'badge neutral', label: m.label, title: m.title });
  }
  return out;
}

/**
 * Muted metadata at the end of a row (never badges): where the item lives (only where the
 * list mixes projects) and when it was last updated. Each part is `{ key, label, title, icon? }`.
 */
export function itemMeta(it, { where = '' } = {}) {
  if (!it) return [];
  const out = [];
  if (where) out.push({ key: 'where', label: where, title: 'Where it lives' });
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

/**
 * Unified links as text, one per line:
 *   item link:   "-> rule/money (depends_on)"
 *   url link:    "Title | https://url"  (or just the url)
 *   path link:   "path: src/payments/**"
 */
export function linksToText(links) {
  return (links || [])
    .map((l) => {
      if (l.item) return `-> ${l.item} (${l.rel || 'relates_to'})`;
      if (l.path) return `path: ${l.path}`;
      return l.title && l.title !== l.url ? `${l.title} | ${l.url}` : l.url;
    })
    .join('\n');
}

export function textToLinks(text) {
  return String(text || '')
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const itemMatch = line.match(/^->\s*(\S+)\s*\(([a-z_]+)\)\s*$/);
      if (itemMatch) return { item: itemMatch[1], rel: itemMatch[2] };
      const pathMatch = line.match(/^path:\s*(.+)$/);
      if (pathMatch) return { path: pathMatch[1].trim() };
      const i = line.lastIndexOf('|');
      if (i < 0) return { url: line };
      const title = line.slice(0, i).trim();
      const url = line.slice(i + 1).trim();
      return title ? { title, url } : { url };
    });
}
