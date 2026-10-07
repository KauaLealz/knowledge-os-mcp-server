// Grafo de relações do workspace: items como nós, relations como arestas.
// Layout force-directed simples (repulsão + atração por aresta + gravidade leve ao
// centro), sem biblioteca externa — SVG puro, posições calculadas de uma vez em load().
import { api } from '../api.js';
import { go } from '../router.js';
import { typeClass } from '../util.js';

const WIDTH = 900;
const HEIGHT = 560;
const PADDING = 26;
const MAX_ITER = 200;
const MOVE_EPS = 0.08; // movimento médio por nó abaixo disso: já estabilizou

/** Calcula x/y de cada nó em `nodes` (mutados in-place). */
function layout(nodes, edges) {
  const n = nodes.length;
  if (!n) return;
  const cx = WIDTH / 2;
  const cy = HEIGHT / 2;
  const k = Math.sqrt((WIDTH * HEIGHT) / n) * 0.9; // distância ideal entre nós
  const byId = new Map(nodes.map((d) => [d.id, d]));

  for (const node of nodes) {
    const angle = Math.random() * Math.PI * 2;
    const r = Math.min(WIDTH, HEIGHT) / 3;
    node.x = cx + Math.cos(angle) * r;
    node.y = cy + Math.sin(angle) * r;
    node.vx = 0;
    node.vy = 0;
  }

  for (let iter = 0; iter < MAX_ITER; iter++) {
    // Repulsão entre todo par de nós (como cargas elétricas iguais).
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const a = nodes[i];
        const b = nodes[j];
        const ddx = a.x - b.x;
        const ddy = a.y - b.y;
        const dist = Math.sqrt(ddx * ddx + ddy * ddy) || 0.01;
        const force = (k * k) / dist;
        const fx = (ddx / dist) * force;
        const fy = (ddy / dist) * force;
        a.vx += fx;
        a.vy += fy;
        b.vx -= fx;
        b.vy -= fy;
      }
    }
    // Atração nas arestas (como uma mola puxando os dois lados).
    for (const e of edges) {
      const a = byId.get(e.source);
      const b = byId.get(e.target);
      if (!a || !b) continue;
      const ddx = a.x - b.x;
      const ddy = a.y - b.y;
      const dist = Math.sqrt(ddx * ddx + ddy * ddy) || 0.01;
      const force = (dist * dist) / k;
      const fx = (ddx / dist) * force;
      const fy = (ddy / dist) * force;
      a.vx -= fx;
      a.vy -= fy;
      b.vx += fx;
      b.vy += fy;
    }
    // Gravidade leve ao centro (evita que o grafo derive pra fora da viewBox) + amortecimento.
    let moved = 0;
    for (const node of nodes) {
      node.vx += (cx - node.x) * 0.012;
      node.vy += (cy - node.y) * 0.012;
      node.vx *= 0.85;
      node.vy *= 0.85;
      node.x = Math.min(WIDTH - PADDING, Math.max(PADDING, node.x + node.vx));
      node.y = Math.min(HEIGHT - PADDING, Math.max(PADDING, node.y + node.vy));
      moved += Math.abs(node.vx) + Math.abs(node.vy);
    }
    if (moved / n < MOVE_EPS) break;
  }
}

export function register(Alpine) {
  Alpine.data('graphView', () => ({
    nodes: [],
    edges: [],
    loading: true,
    error: null,
    width: WIDTH,
    height: HEIGHT,

    get app() {
      return Alpine.store('app');
    },

    init() {
      this.$watch(
        () => this.app.route.params.ws,
        () => this.load(),
      );
      this.load();
    },

    async load() {
      const wsId = this.app.route.params.ws;
      if (!wsId) return;
      this.loading = true;
      this.error = null;
      try {
        const data = await api('GET', `/workspaces/${wsId}/graph`);
        const nodes = (data.nodes || []).map((n) => ({ ...n }));
        const edges = data.edges || [];
        layout(nodes, edges);
        this.nodes = nodes;
        this.edges = edges;
      } catch (e) {
        this.nodes = [];
        this.edges = [];
        this.error = e.message;
      } finally {
        this.loading = false;
      }
    },

    byId(id) {
      return this.nodes.find((n) => n.id === id);
    },

    nodeClass(n) {
      return 'gnode ' + typeClass(n.type);
    },

    edgeClass(e) {
      return e.relation_type === 'supersedes' ? 'gedge supersedes' : 'gedge';
    },

    label(title) {
      return title.length > 22 ? title.slice(0, 21) + '…' : title;
    },

    goTo(id) {
      const href = this.app.hItemById(id);
      if (href) go(href);
    },
  }));
}
