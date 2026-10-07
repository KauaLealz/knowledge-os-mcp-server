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
const MAX_RADIUS = 16;
// Tamanho mínimo de célula por project na grade do workspace: grande o bastante pra caber
// um rótulo + sub-grupos de assunto sem amontoar. Com mais projects, o canvas cresce (zoom
// e pan já dão conta de navegar nele), em vez de espremer tudo no mesmo 900x560.
const PROJECT_CELL_W = 340;
const PROJECT_CELL_H = 260;

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
      if (!this.nodes.length) {
        while (svg.firstChild) svg.removeChild(svg.firstChild);
        return;
      }

      // Agrupamento em duas camadas: no grafo do workspace, cada project vira uma região
      // maior numa grade; dentro de cada região, os assuntos daquele project (mais um balde
      // "Sem assunto" pros itens soltos) formam sub-regiões menores, só na metade de baixo
      // da região (a de cima é reservada pro rótulo do project, senão um cobre o outro). No
      // grafo de um project só, não existe nível de project (seria redundante) — vai direto
      // pro nível de assunto, usando o canvas inteiro como região única. No grafo de um
      // assunto, nada disso entra: já é um grupo só.
      const scope = this.app.route.name;
      const projectKey = (n) => n.project_id;
      const projectLabel = (n) => n.project_name;
      const subjectKey = (n) => `${n.project_id}:${n.subject_id || 'none'}`;
      const subjectLabel = (n) => (n.subject_id ? n.subject_name : 'Sem assunto');

      // Canvas cresce com o nº de projects: cada um precisa de espaço de verdade pro
      // rótulo e pros sub-grupos de assunto não ficarem espremidos. Zoom/pan (d3-zoom) já
      // dão conta de navegar num canvas maior que a tela.
      const projectIds = scope === 'graph' ? [...new Set(this.nodes.map(projectKey))] : [];
      if (projectIds.length > 1) {
        const cols = Math.ceil(Math.sqrt(projectIds.length));
        const rows = Math.ceil(projectIds.length / cols);
        this.width = Math.max(WIDTH, cols * PROJECT_CELL_W);
        this.height = Math.max(HEIGHT, rows * PROJECT_CELL_H);
      } else {
        this.width = WIDTH;
        this.height = HEIGHT;
      }
      svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      while (svg.firstChild) svg.removeChild(svg.firstChild);

      const viewport = document.createElementNS(SVG_NS, 'g');
      viewport.setAttribute('class', 'graph-viewport');
      svg.appendChild(viewport);

      // Grade genérica: distribui `keys` dentro de uma região retangular, com uma margem
      // (fração da região) deixando um respiro visível entre clusters vizinhos. Só serve
      // pra mirar a força de atração (x-project/x-subject) — não decide onde o rótulo vai
      // (isso só dá pra saber depois que a simulação assentar de verdade, ver mais abaixo).
      const gridCenters = (keys, region, margin) => {
        const cols = Math.ceil(Math.sqrt(keys.length));
        const rows = Math.ceil(keys.length / cols);
        const w = region.w * (1 - margin * 2);
        const h = region.h * (1 - margin * 2);
        const originX = region.x - w / 2;
        const originY = region.y - h / 2;
        return new Map(
          keys.map((k, i) => [
            k,
            {
              x: originX + (w / cols) * ((i % cols) + 0.5),
              y: originY + (h / rows) * (Math.floor(i / cols) + 0.5),
              w: w / cols,
              h: h / rows,
            },
          ]),
        );
      };

      let projectCenters = null;
      if (projectIds.length > 1) {
        projectCenters = gridCenters(projectIds, { x: this.width / 2, y: this.height / 2, w: this.width, h: this.height }, 0.04);
      }

      let subjectCenters = null;
      if (scope === 'graph' || scope === 'project-graph') {
        subjectCenters = new Map();
        const parents = scope === 'graph' ? projectIds : [null];
        for (const parent of parents) {
          const nodesIn = parent === null ? this.nodes : this.nodes.filter((n) => projectKey(n) === parent);
          const keys = [...new Set(nodesIn.map(subjectKey))];
          if (keys.length < 2) continue;
          const full = parent !== null
            ? projectCenters.get(parent)
            : { x: this.width / 2, y: this.height / 2, w: this.width, h: this.height };
          const centers = gridCenters(keys, full, 0.1);
          for (const [k, c] of centers) subjectCenters.set(k, c);
        }
        if (subjectCenters.size === 0) subjectCenters = null;
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
        .force('charge', forceManyBody().strength(-180))
        .force('link', forceLink(links).distance(85).strength(0.4))
        .force('center', forceCenter(this.width / 2, this.height / 2))
        .force('collide', forceCollide((n) => radius(n) + 10))
        .on('tick', tick);

      // Força fraca pro centro do project (a região grande) e, por cima, uma força um pouco
      // mais forte pro centro do sub-grupo de assunto dentro dela — o resultado é o
      // aninhamento: o assunto puxa mais, mas o project continua por perto. As duas são
      // propositalmente fracas (não uma gaiola rígida): a repulsão entre nós (charge) ganha
      // espaço pra espalhar o grupo em vez de empilhar tudo em cima do rótulo.
      if (projectCenters) {
        this.sim
          .force('x-project', forceX((n) => projectCenters.get(projectKey(n)).x).strength(0.05))
          .force('y-project', forceY((n) => projectCenters.get(projectKey(n)).y).strength(0.05));
      }
      if (subjectCenters) {
        this.sim
          .force('x-subject', forceX((n) => (subjectCenters.get(subjectKey(n)) || projectCenters?.get(projectKey(n)) || { x: this.width / 2 }).x).strength(0.1))
          .force('y-subject', forceY((n) => (subjectCenters.get(subjectKey(n)) || projectCenters?.get(projectKey(n)) || { y: this.height / 2 }).y).strength(0.1));
      }

      // Deixa o layout assentar de uma vez antes do primeiro desenho: o timer do d3 usa
      // requestAnimationFrame, que o navegador pausa se a aba abrir em segundo plano — sem
      // isso, o grafo ficaria com todos os nós empilhados até alguém olhar pra aba.
      this.sim.stop();
      for (let i = 0; i < 150; i++) this.sim.tick();
      tick();
      this.sim.stop();

      // Rótulos por hierarquia — galáxia (workspace) > planeta (project) > país (assunto) —
      // colados em cima de onde os nós REALMENTE pararam (não uma célula fixa da grade: a
      // física é frouxa de propósito e o grupo se espalha além da célula nominal). Cada um
      // fica o mais perto possível do próprio aglomerado (BASE_GAP), mas um país pode ser o
      // próprio ponto mais alto do seu project (ou um project, do workspace inteiro) — nesse
      // caso o rótulo de fora empurra pra cima só o suficiente pra não empacar no de dentro,
      // em vez de ficar sempre numa distância fixa (que ou sobrepõe, ou afasta à toa quando
      // não tem ninguém por perto). Desenhados por último: pintam por cima de nós e linhas
      // (linhas podem passar por baixo de um rótulo sem problema; um nó, nunca).
      const BASE_GAP = 12;
      const HALF_HEIGHT = { galaxy: 12, planet: 9, country: 7 };
      const STACK_GAP = 4;

      const bbox = (ns) => {
        let minX = Infinity, maxX = -Infinity, minY = Infinity;
        for (const n of ns) {
          if (n.x < minX) minX = n.x;
          if (n.x > maxX) maxX = n.x;
          if (n.y < minY) minY = n.y;
        }
        return { cx: (minX + maxX) / 2, top: minY };
      };
      const addClusterLabel = (cls, tier, ns, text, ceiling) => {
        if (!ns.length) return null;
        const { cx, top } = bbox(ns);
        const natural = top - MAX_RADIUS - BASE_GAP;
        const y = ceiling === null ? natural : Math.min(natural, ceiling);
        const label = document.createElementNS(SVG_NS, 'text');
        label.setAttribute('class', cls);
        label.setAttribute('x', String(cx));
        label.setAttribute('y', String(y));
        label.textContent = text;
        viewport.appendChild(label);
        return y;
      };

      // Por project (não global): um país muito alto só empurra o rótulo do SEU project,
      // nunca o de um project vizinho que não tem nada a ver com aquela colisão.
      const minCountryYByProject = new Map();
      if (subjectCenters) {
        for (const k of subjectCenters.keys()) {
          const ns = this.nodes.filter((n) => subjectKey(n) === k);
          const y = addClusterLabel('gcluster-label gcluster-label-country', 'country', ns, subjectLabel(ns[0]), null);
          if (y !== null) {
            const pid = projectKey(ns[0]);
            const prev = minCountryYByProject.get(pid);
            if (prev === undefined || y < prev) minCountryYByProject.set(pid, y);
          }
        }
      }
      let minGalaxyY = Infinity;
      if (projectCenters) {
        const childClear = HALF_HEIGHT.country + HALF_HEIGHT.planet + STACK_GAP;
        for (const id of projectIds) {
          const ns = this.nodes.filter((n) => projectKey(n) === id);
          const minCountryY = minCountryYByProject.get(id);
          const ceiling = minCountryY === undefined ? null : minCountryY - childClear;
          const y = addClusterLabel('gcluster-label gcluster-label-planet', 'planet', ns, projectLabel(ns[0]), ceiling);
          if (y !== null && y < minGalaxyY) minGalaxyY = y;
        }
      }
      if (scope === 'graph') {
        const childClear = HALF_HEIGHT.planet + HALF_HEIGHT.galaxy + STACK_GAP;
        const ceiling = minGalaxyY === Infinity ? null : minGalaxyY - childClear;
        addClusterLabel('gcluster-label gcluster-label-galaxy', 'galaxy', this.nodes, this.app.workspace?.name || '', ceiling);
      }

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
