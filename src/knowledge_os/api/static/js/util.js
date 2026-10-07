// Small, dependency-free utilities.

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
 * Single map of item types to their display label. No icons — just a colored dot + text.
 * Color comes from the `t-<type>` class (tokens --t-<type> in tokens.css).
 */
export const TYPE_META = {
  rule: { label: 'Rule' },
  insight: { label: 'Decision' },
  procedure: { label: 'Procedure' },
  pattern: { label: 'Pattern' },
  knowledge: { label: 'Learning' },
  context: { label: 'Context' },
  spec: { label: 'Spec' },
  secret: { label: 'Secret' },
};
export const TYPE_ORDER = Object.keys(TYPE_META);
/** Types the user can pick when creating an item (secret is created by the agent; the UI
 * only ever fills in its value). */
export const ITEM_TYPES = TYPE_ORDER.filter((t) => t !== 'secret');

export function typeLabel(type) {
  return TYPE_META[type]?.label || String(type || '');
}
/** Color class (`t-rule`...); unknown type falls back to neutral. */
export function typeClass(type) {
  return TYPE_META[type] ? 't-' + type : 't-unknown';
}
