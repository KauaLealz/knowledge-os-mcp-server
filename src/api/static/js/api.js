// Cliente HTTP: único ponto que conhece token, X-Connection-Id e tratamento de 401.

const TOKEN_KEY = 'kos.token';
let memToken = null; // fallback quando sessionStorage não existe
let connectionId = null;
let onExpired = () => {};

function session() {
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function getToken() {
  const s = session();
  try {
    return (s && s.getItem(TOKEN_KEY)) || memToken;
  } catch {
    return memToken;
  }
}

function setToken(token) {
  memToken = token;
  try {
    const s = session();
    if (s) s.setItem(TOKEN_KEY, token);
  } catch {
    /* sem storage */
  }
}

/** Lê `#token=...`, guarda em sessionStorage e tira o fragmento da barra de endereço. */
export function captureTokenFromUrl() {
  const m = /[#&]token=([^&]*)/.exec(location.hash);
  if (!m) return;
  if (m[1]) setToken(decodeURIComponent(m[1]));
  const rest = location.hash.replace(/[#&]token=[^&]*/, '').replace(/^#&?/, '');
  history.replaceState(null, '', location.pathname + location.search + (rest ? '#' + rest : ''));
}

export function setConnection(id) {
  connectionId = id || null;
}

export function setOnExpired(fn) {
  onExpired = fn;
}

export class ApiError extends Error {
  constructor(status, detail) {
    super(formatDetail(detail) || `Erro ${status}`);
    this.status = status;
    this.detail = detail;
  }
}

function formatDetail(detail) {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((d) => `${(d.loc || []).filter((p) => p !== 'body').join('.')}: ${d.msg}`)
      .join('; ');
  }
  return detail ? JSON.stringify(detail) : '';
}

function buildUrl(path, query) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(query || {})) {
    if (v !== undefined && v !== null && v !== '') qs.set(k, v);
  }
  const s = qs.toString();
  return `/api${path}${s ? '?' + s : ''}`;
}

function headers(extra) {
  const h = { ...extra };
  const token = getToken();
  if (token) h.Authorization = `Bearer ${token}`;
  if (connectionId) h['X-Connection-Id'] = connectionId;
  return h;
}

async function request(method, path, { body, query } = {}) {
  const init = { method, headers: headers(body !== undefined ? { 'Content-Type': 'application/json' } : {}) };
  if (body !== undefined) init.body = JSON.stringify(body);
  let res;
  try {
    res = await fetch(buildUrl(path, query), init);
  } catch {
    throw new ApiError(0, 'Sem conexão com o servidor.');
  }
  if (res.status === 401) {
    onExpired();
    throw new ApiError(401, 'Sessão expirada');
  }
  return res;
}

export async function api(method, path, opts) {
  const res = await request(method, path, opts);
  if (res.status === 204) return null;
  let data = null;
  try {
    data = await res.json();
  } catch {
    /* corpo vazio ou não JSON */
  }
  if (!res.ok) throw new ApiError(res.status, data && data.detail);
  return data;
}

/** Baixa um recurso binário (artifact) com o header de autenticação e dispara o download. */
export async function download(path, filename) {
  const res = await request('GET', path);
  if (!res.ok) throw new ApiError(res.status, 'Falha ao baixar o arquivo');
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
