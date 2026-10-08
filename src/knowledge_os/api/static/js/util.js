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

/** Who wrote the item. The glyph is text (not an SVG icon), so lists stay icon-free. */
export const ORIGIN_META = {
  user: { label: 'User', glyph: '●' },
  code: { label: 'Code', glyph: '⌘' },
  agent: { label: 'Agent', glyph: '◆' },
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
  const o = ORIGIN_META[origin];
  return o ? `${o.glyph} ${o.label}` : String(origin || '');
}

/**
 * Scope as shown on items, projects and subjects: the effective one, plus where it comes from
 * when it is inherited (effective ≠ explicit). `inheritedFrom` is the API's
 * `scope_inherited_from` (subject | project | workspace | null).
 */
export function scopeText(effective, explicit, inheritedFrom) {
  const label = scopeLabel(effective);
  if (explicit) return label;
  if (inheritedFrom) return `${label} (inherited from ${inheritedFrom})`;
  return `${label} (default)`;
}

/** Scope of an item from any API shape: the full item (`effective_scope` + explicit `scope` +
 * `scope_inherited_from`) or a search/tree row (`scope` = already the effective one). */
export function itemScope(it) {
  if (!it) return '';
  if ('effective_scope' in it) return scopeText(it.effective_scope, it.scope, it.scope_inherited_from);
  return scopeLabel(it.scope);
}
/** Is the shown scope inherited (no explicit scope on the item itself)? */
export function scopeInherited(it) {
  return !!it && 'effective_scope' in it && !it.scope;
}

/** Item in review: shown after the others in search and marked ⚠ everywhere. */
export function isReview(it) {
  return it?.status === 'review';
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
