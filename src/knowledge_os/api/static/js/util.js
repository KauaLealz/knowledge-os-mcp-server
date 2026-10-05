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

/**
 * Mapa único dos tipos: rótulo PT-BR, plural (cabeçalho de grupo) e ícone do sprite.
 * A cor vem da classe `t-<tipo>` (tokens --t-<tipo> em tokens.css).
 * A ordem das chaves é a ordem fixa dos grupos nas listas.
 */
export const TYPE_META = {
  rule: { label: 'Regra', plural: 'Regras', icon: 'rule' },
  insight: { label: 'Decisão', plural: 'Decisões', icon: 'insight' },
  procedure: { label: 'Procedimento', plural: 'Procedimentos', icon: 'procedure' },
  pattern: { label: 'Padrão', plural: 'Padrões', icon: 'pattern' },
  knowledge: { label: 'Aprendizado', plural: 'Aprendizados', icon: 'knowledge' },
  context: { label: 'Contexto', plural: 'Contexto', icon: 'context' },
  task: { label: 'Mudança', plural: 'Mudanças', icon: 'task' },
  artifact: { label: 'Anexo', plural: 'Anexos', icon: 'artifact' },
  secret: { label: 'Segredo', plural: 'Segredos', icon: 'secret' },
};
export const TYPE_ORDER = Object.keys(TYPE_META);
/** Tipos que o usuário pode escolher ao criar um item (segredo ainda não é criado pela UI). */
export const ITEM_TYPES = TYPE_ORDER.filter((t) => t !== 'secret');

/** Nome do símbolo do sprite para um type (cai em "knowledge"). */
export function typeIcon(type) {
  return TYPE_META[type]?.icon || 'knowledge';
}
export function typeLabel(type) {
  return TYPE_META[type]?.label || String(type || '');
}
export function typePlural(type) {
  return TYPE_META[type]?.plural || String(type || '');
}
/** Classe de cor (`t-rule`...); tipo desconhecido fica neutro. */
export function typeClass(type) {
  return TYPE_META[type] ? 't-' + type : 't-unknown';
}

/** Agrupa por tipo na ordem fixa; grupos vazios não aparecem; tipos fora do mapa vão ao fim. */
export function groupByType(items) {
  const by = new Map();
  for (const it of items) {
    if (!by.has(it.type)) by.set(it.type, []);
    by.get(it.type).push(it);
  }
  const known = TYPE_ORDER.filter((t) => by.has(t));
  const extra = [...by.keys()].filter((t) => !TYPE_META[t]).sort();
  return [...known, ...extra].map((type) => ({
    type,
    label: typePlural(type),
    items: by.get(type),
  }));
}
