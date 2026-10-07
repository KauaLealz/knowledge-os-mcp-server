// Router por hash: #/c/:conn/w/:ws/p/:pj/i/:item[/edit] e #/settings/connections[/:id|/new].

const enc = encodeURIComponent;

/** Interpreta um hash em { name, params }. */
export function parseHash(hash = location.hash) {
  const path = hash.replace(/^#/, '').split('?')[0];
  const seg = path.split('/').filter(Boolean).map((s) => {
    try {
      return decodeURIComponent(s);
    } catch {
      return s;
    }
  });
  if (seg.length === 0) return { name: 'home', params: {} };
  if (seg[0] === 'settings') {
    if (seg[1] === 'connections') return { name: 'connections', params: { sub: seg[2] || null } };
    return { name: 'notfound', params: {} };
  }
  if (seg[0] !== 'c' || !seg[1]) return { name: 'notfound', params: {} };
  const params = { conn: seg[1] };
  if (seg.length === 2) return { name: 'connection', params };
  if (seg[2] !== 'w' || !seg[3]) return { name: 'notfound', params };
  params.ws = seg[3];
  if (seg.length === 4) return { name: 'workspace', params };
  // Segmento "graph": grafo de relações do workspace, sem id próprio (irmão de "p").
  if (seg[4] === 'graph' && seg.length === 5) return { name: 'graph', params };
  // Segmento "p" (project): era "d" (domain) antes do rename; "pj" evita colidir com "ws".
  if (seg[4] !== 'p' || !seg[5]) return { name: 'notfound', params };
  params.pj = seg[5];
  if (seg.length === 6) return { name: 'project', params };
  if (seg[6] !== 'i' || !seg[7]) return { name: 'notfound', params };
  params.item = seg[7];
  if (seg.length === 8) return { name: 'item', params };
  if (seg.length === 9 && seg[8] === 'edit') return { name: 'item', params: { ...params, edit: true } };
  return { name: 'notfound', params };
}

export const hrefs = {
  conn: (c) => `#/c/${enc(c)}`,
  ws: (c, w) => `#/c/${enc(c)}/w/${enc(w)}`,
  graph: (c, w) => `#/c/${enc(c)}/w/${enc(w)}/graph`,
  project: (c, w, p) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}`,
  item: (c, w, p, i) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/i/${enc(i)}`,
  edit: (c, w, p, i) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/i/${enc(i)}/edit`,
  connections: (sub) => `#/settings/connections${sub ? '/' + enc(sub) : ''}`,
};

export function go(hash) {
  if (location.hash === hash) return;
  location.hash = hash;
}
