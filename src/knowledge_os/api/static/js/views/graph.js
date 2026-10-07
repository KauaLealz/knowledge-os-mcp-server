// Grafo de relações (workspace, project ou subject — a rota decide o escopo). Física de
// layout via d3-force, pan/zoom via d3-zoom, arrastar nó via d3-drag (bundles vendorizados
// em vendor/, sem CDN em runtime). DOM sempre via createElementNS/setAttribute — nunca
// atribuição direta de marcação bruta (x-html), mesma regra do resto do app (markdown.js é
// a única exceção, com DOMPurify).
import { api } from '../api.js';
import { go, hrefs } from '../router.js';
import { typeClass } from '../util.js';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation, forceX, forceY } from '../../vendor/d3-force.esm.js';
import { select } from '../../vendor/d3-selection.esm.js';
import { drag } from '../../vendor/d3-drag.esm.js';
import { zoom } from '../../vendor/d3-zoom.esm.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const WIDTH = 900;
const HEIGHT = 560;

export function register(Alpine) {
  Alpine.data('graphView', () => ({
    nodes: [],
    edges: [],
    loading: true,
    error: null,
    width: WIDTH,
    height: HEIGHT,
    sim: null, // fora do estado reativo seria melhor, mas Alpine não reage a isto de qualquer forma

    get app() {
      return Alpine.store('app');
    },

    /** Escopo pela rota: workspace sempre; project/subject quando a rota é mais específica. */
    get scopeQuery() {
      const p = this.app.route.params;
      const q = {};
      if (this.app.route.name === 'project-graph' || this.app.route.name === 'subject-graph') {
        q.project_id = p.pj;
      }
      if (this.app.route.name === 'subject-graph') q.subject_id = p.subj;
      return q;
    },

    init() {
      this.$watch(
        () => this.app.route.name + '|' + this.app.route.params.ws + '|' + this.app.route.params.pj + '|' + this.app.route.params.subj,
        () => this.load(),
      );
      this.load();
    },

    destroy() {
      this.sim?.stop();
    },

    async load() {
      const wsId = this.app.route.params.ws;
      if (!wsId) return;
      this.loading = true;
      this.error = null;
      this.sim?.stop();
      try {
        const data = await api('GET', `/workspaces/${wsId}/graph`, { query: this.scopeQuery });
        this.nodes = (data.nodes || []).map((n) => ({ ...n }));
        this.edges = (data.edges || []).map((e) => ({ ...e }));
      } catch (e) {
        this.nodes = [];
        this.edges = [];
        this.error = e.message;
      } finally {
        this.loading = false;
      }
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

    /** Não depende de itemIndex (só tem o que a sidebar já carregou): o próprio nó do grafo
     * já traz workspace/project, suficiente pra montar o link direto. */
    goTo(n) {
      go(hrefs.item(this.app.connId, this.app.route.params.ws, n.project_id, n.id));
    },

    /**
     * Monta o SVG uma vez (createElementNS/setAttribute — nunca marcação bruta) e entrega
     * posição/pan/zoom/arrastar pro d3: forceSimulation cuida do layout a cada tick (só
     * atualiza atributos, não recria elementos), d3-zoom cuida de roda-pra-zoom e arrastar o
     * fundo, d3-drag cuida de arrastar um nó (fixa a posição enquanto arrasta, solta no fim
     * pra simulação relaxar de novo).
     */
    renderSvg(svg) {
      this.sim?.stop();
      svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      while (svg.firstChild) svg.removeChild(svg.firstChild);
      if (!this.nodes.length) return;

      const viewport = document.createElementNS(SVG_NS, 'g');
      viewport.setAttribute('class', 'graph-viewport');
      svg.appendChild(viewport);

      // No grafo do workspace (vários projects ao mesmo tempo), agrupa visualmente por
      // project/assunto — cada grupo puxado pro centro de uma célula de uma grade, com um
      // rótulo atrás dos nós indicando de qual project/assunto se trata. Escopo de
      // project/subject já é um grupo só, não precisa disso.
      const groupKey = (n) => (n.subject_id ? `${n.project_id}:${n.subject_id}` : n.project_id);
      const groupLabel = (n) => (n.subject_id ? `${n.project_name} · ${n.subject_name}` : n.project_name);
      const groups = this.app.route.name === 'graph' ? [...new Set(this.nodes.map(groupKey))] : [];
      let clusterCenters = null;
      if (groups.length > 1) {
        const cols = Math.ceil(Math.sqrt(groups.length));
        const rows = Math.ceil(groups.length / cols);
        const cellW = this.width / cols;
        const cellH = this.height / rows;
        clusterCenters = new Map(
          groups.map((g, i) => [
            g,
            { x: cellW * ((i % cols) + 0.5), y: cellH * (Math.floor(i / cols) + 0.5) },
          ]),
        );
        const labelByGroup = new Map(this.nodes.map((n) => [groupKey(n), groupLabel(n)]));
        for (const g of groups) {
          const c = clusterCenters.get(g);
          const label = document.createElementNS(SVG_NS, 'text');
          label.setAttribute('class', 'gcluster-label');
          label.setAttribute('x', String(c.x));
          label.setAttribute('y', String(c.y));
          label.textContent = labelByGroup.get(g);
          viewport.appendChild(label);
        }
      }

      const edgeEls = this.edges.map((e) => {
        const line = document.createElementNS(SVG_NS, 'line');
        line.setAttribute('class', this.edgeClass(e));
        viewport.appendChild(line);
        return line;
      });

      // Grau (nº de arestas) de cada nó: raio e espessura do nome acompanham, como no
      // Obsidian — um hub muito conectado chama mais atenção que uma folha solta.
      const degree = new Map(this.nodes.map((n) => [n.id, 0]));
      for (const e of this.edges) {
        degree.set(e.source, (degree.get(e.source) || 0) + 1);
        degree.set(e.target, (degree.get(e.target) || 0) + 1);
      }
      const radius = (n) => Math.min(16, 4 + Math.sqrt(degree.get(n.id) || 0) * 2.2);

      const nodeEls = this.nodes.map((n) => {
        const g = document.createElementNS(SVG_NS, 'g');
        g.setAttribute('class', this.nodeClass(n));
        const title = document.createElementNS(SVG_NS, 'title');
        title.textContent = n.title;
        const circle = document.createElementNS(SVG_NS, 'circle');
        circle.setAttribute('r', String(radius(n)));
        const text = document.createElementNS(SVG_NS, 'text');
        text.setAttribute('x', String(radius(n) + 4));
        text.setAttribute('y', '4');
        text.textContent = this.label(n.title);
        g.append(title, circle, text);
        g.addEventListener('pointerenter', () => g.classList.add('hover'));
        g.addEventListener('pointerleave', () => g.classList.remove('hover'));
        viewport.appendChild(g);
        return g;
      });

      const byId = new Map(this.nodes.map((n) => [n.id, n]));
      const links = this.edges
        .map((e) => ({ ...e, source: byId.get(e.source), target: byId.get(e.target) }))
        .filter((e) => e.source && e.target);

      const tick = () => {
        edgeEls.forEach((line, i) => {
          const e = links[i];
          if (!e) return;
          line.setAttribute('x1', e.source.x);
          line.setAttribute('y1', e.source.y);
          line.setAttribute('x2', e.target.x);
          line.setAttribute('y2', e.target.y);
        });
        nodeEls.forEach((g, i) => {
          const n = this.nodes[i];
          g.setAttribute('transform', `translate(${n.x},${n.y})`);
        });
      };

      this.sim = forceSimulation(this.nodes)
        .force('charge', forceManyBody().strength(-160))
        .force('link', forceLink(links).distance(70).strength(0.4))
        .force('center', forceCenter(this.width / 2, this.height / 2))
        .force('collide', forceCollide((n) => radius(n) + 6))
        .on('tick', tick);

      if (clusterCenters) {
        this.sim
          .force('x', forceX((n) => clusterCenters.get(groupKey(n)).x).strength(0.12))
          .force('y', forceY((n) => clusterCenters.get(groupKey(n)).y).strength(0.12));
      }

      // Deixa o layout assentar de uma vez antes do primeiro desenho: o timer do d3 usa
      // requestAnimationFrame, que o navegador pausa se a aba abrir em segundo plano — sem
      // isso, o grafo ficaria com todos os nós empilhados até alguém olhar pra aba.
      this.sim.stop();
      for (let i = 0; i < 150; i++) this.sim.tick();
      tick();
      this.sim.stop();

      // Clique abre o item; arrastar não deve contar como clique (d3-drag não distingue,
      // então só navega se o nó não se mexeu entre mousedown e mouseup).
      nodeEls.forEach((g, i) => {
        const n = this.nodes[i];
        let moved = false;
        select(g).call(
          drag()
            .on('start', (event) => {
              moved = false;
              if (!event.active) this.sim.alphaTarget(0.3).restart();
              n.fx = n.x;
              n.fy = n.y;
            })
            .on('drag', (event) => {
              moved = true;
              n.fx = event.x;
              n.fy = event.y;
            })
            .on('end', () => {
              this.sim.alphaTarget(0);
              n.fx = null;
              n.fy = null;
              if (!moved) this.goTo(n);
            }),
        );
      });

      // Roda do mouse = zoom; arrastar o fundo = pan. scaleExtent evita zoom absurdo.
      // Não chama zoomBehavior.transform pra fixar o identity inicial: isso dispara
      // selection.interrupt() por dentro do d3-zoom, que só existe depois de importar
      // d3-transition — sem transição nenhuma rolando, o transform já nasce "sem nada"
      // (equivalente a identity), não precisa setar explicitamente.
      const zoomBehavior = zoom()
        .scaleExtent([0.2, 5])
        .on('zoom', (event) => {
          viewport.setAttribute('transform', String(event.transform));
        });
      select(svg).call(zoomBehavior);
    },
  }));
}
