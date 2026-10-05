// Utilitários pequenos e sem dependências.

/** localStorage com try/catch: a página funciona sem storage. */
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
    /* sem storage: ignora */
  }
}

/** A API devolve datetimes UTC sem fuso (utcnow): assume UTC quando não há. */
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
  if (sec < 45) return 'agora';
  if (sec < 3600) return `há ${Math.max(1, Math.round(sec / 60))} min`;
  if (sec < 86400) return `há ${Math.round(sec / 3600)} h`;
  if (sec < 2592000) return `há ${Math.round(sec / 86400)} d`;
  if (sec < 31536000) {
    const m = Math.round(sec / 2592000);
    return `há ${m} ${m > 1 ? 'meses' : 'mês'}`;
  }
  return `há ${Math.round(sec / 31536000)} a`;
}

export function formatDate(value) {
  const d = parseDate(value);
  return d ? d.toLocaleString('pt-BR', { dateStyle: 'medium', timeStyle: 'short' }) : '';
}

export const ITEM_TYPES = [
  'context', 'rule', 'pattern', 'procedure', 'knowledge', 'insight', 'artifact', 'task',
];
export const MEMORY_CLASSES = ['ephemeral', 'working', 'longterm', 'canonical'];

const KNOWN_TYPES = new Set(ITEM_TYPES);
/** Nome do símbolo do sprite para um type (cai em "knowledge"). */
export function typeIcon(type) {
  return KNOWN_TYPES.has(type) ? type : 'knowledge';
}

export function confidenceLevel(c) {
  if (c == null) return 'none';
  if (c < 60) return 'low';
  if (c < 85) return 'mid';
  return 'high';
}
