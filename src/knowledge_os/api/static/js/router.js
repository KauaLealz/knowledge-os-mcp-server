// Router por hash: #/c/:conn/w/:ws/p/:pj/i/:item[/edit], #/c/:conn/w/:ws/p/:pj/s/:subj,
// #/c/:conn/w/:ws[/p/:pj[/s/:subj]]/graph, #/c/:conn/tags e #/settings/connections[/:id].

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
  // Tags gerenciadas: valem para a conexão inteira (não são de um workspace).
  if (seg[2] === 'tags' && seg.length === 3) return { name: 'tags', params };
  if (seg[2] !== 'w' || !seg[3]) return { name: 'notfound', params };
  params.ws = seg[3];
  if (seg.length === 4) return { name: 'workspace', params };
  // Segmento "graph": grafo de relações do workspace, sem id próprio (irmão de "p").
  if (seg[4] === 'graph' && seg.length === 5) return { name: 'graph', params };
  // Segmento "p" (project): era "d" (domain) antes do rename; "pj" evita colidir com "ws".
  if (seg[4] !== 'p' || !seg[5]) return { name: 'notfound', params };
  params.pj = seg[5];
  if (seg.length === 6) return { name: 'project', params };
  // Grafo do project: irmão de "i"/"s", sem id próprio.
  if (seg[6] === 'graph' && seg.length === 7) return { name: 'project-graph', params };
  // Segmento "s" (subject): página do assunto, com o próprio grafo escopado como filho.
  if (seg[6] === 's' && seg[7]) {
    params.subj = seg[7];
    if (seg.length === 8) return { name: 'subject', params };
    if (seg.length === 9 && seg[8] === 'graph') return { name: 'subject-graph', params };
    return { name: 'notfound', params };
  }
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
  projectGraph: (c, w, p) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/graph`,
  subject: (c, w, p, s) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/s/${enc(s)}`,
  subjectGraph: (c, w, p, s) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/s/${enc(s)}/graph`,
  item: (c, w, p, i) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/i/${enc(i)}`,
  edit: (c, w, p, i) => `#/c/${enc(c)}/w/${enc(w)}/p/${enc(p)}/i/${enc(i)}/edit`,
  tags: (c) => `#/c/${enc(c)}/tags`,
  connections: (sub) => `#/settings/connections${sub ? '/' + enc(sub) : ''}`,
};

export function go(hash) {
  if (location.hash === hash) return;
  location.hash = hash;
}
