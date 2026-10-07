// Grafo de relações (workspace, project ou subject — a rota decide o escopo). Tudo é nó e
// aresta — inclusive project e assunto, que entram como nós próprios (quadrado maior pra
// project, triângulo pra assunto, círculo pequeno pro item, como já era) ligados aos itens
// por arestas de hierarquia. A física (d3-force) já clusteriza sozinha a partir dessas
// arestas — não precisa de nenhuma grade nominal, força de agrupamento à parte nem contorno
// desenhado por fora: é o mesmo grafo, só que com nós de tamanho e forma diferentes.
// Pan/zoom via d3-zoom, arrastar nó via d3-drag (bundles vendorizados em vendor/, sem CDN em
// runtime). DOM sempre via createElementNS/setAttribute — nunca atribuição direta de
// marcação bruta (x-html), mesma regra do resto do app (markdown.js é a única exceção, com
// DOMPurify).
import { api } from '../api.js';
import { go, hrefs } from '../router.js';
import { typeClass } from '../util.js';
import { forceCenter, forceCollide, forceLink, forceManyBody, forceSimulation } from '../../vendor/d3-force.esm.js';
import { select } from '../../vendor/d3-selection.esm.js';
import { drag } from '../../vendor/d3-drag.esm.js';
import { zoom } from '../../vendor/d3-zoom.esm.js';

const SVG_NS = 'http://www.w3.org/2000/svg';
const WIDTH = 900;
const HEIGHT = 560;
// Item (círculo) varia de 4 a 16 pelo grau; project/assunto têm raio fixo, maior que o
// teto do item — nunca devem parecer menores que um item bem conectado.
const RADIUS = { project: 26, subject: 20 };

/** Hash determinístico de um id pra um matiz (0-359) — mesmo id sempre a mesma cor, entre
 * recarregamentos. */
function hueOf(id) {
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 360;
}

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
      if (n.kind === 'project') return 'gnode gnode-project';
      if (n.kind === 'subject') return 'gnode gnode-subject';
      return 'gnode ' + typeClass(n.type);
    },

    edgeClass(e) {
      if (e.kind === 'hierarchy') return 'gedge gedge-hierarchy';
      return e.relation_type === 'supersedes' ? 'gedge supersedes' : 'gedge';
    },

    label(title) {
      return title.length > 22 ? title.slice(0, 21) + '…' : title;
    },

    /** Item não depende de itemIndex (só tem o que a sidebar já carregou): o próprio nó do
     * grafo já traz workspace/project, suficiente pra montar o link direto. Project e
     * assunto são nós próprios agora — clicar neles abre a página deles, não a de um item. */
    goTo(n) {
      const ws = this.app.route.params.ws;
      if (n.kind === 'project') return go(hrefs.project(this.app.connId, ws, n.project_id));
      if (n.kind === 'subject') return go(hrefs.subject(this.app.connId, ws, n.project_id, n.subject_id));
      go(hrefs.item(this.app.connId, ws, n.project_id, n.id));
    },

    /**
     * Project e assunto viram nós de hierarquia: um por project (quadrado) e um por grupo
     * de assunto dentro dele (triângulo, só quando o project tem 2+ grupos — "Sem assunto"
     * conta como um grupo; com só um grupo, os itens ligam direto no project, um nó de
     * assunto ali seria redundante). No grafo de um project só, o nó de project em si seria
     * redundante (já é a página corrente) — só entram os nós de assunto. No grafo de um
     * assunto só, nada disso entra: já é um grupo só.
     */
    hierarchyNodesAndEdges() {
      const scope = this.app.route.name;
      const extraNodes = [];
      const extraEdges = [];
      if (scope !== 'graph' && scope !== 'project-graph') return { extraNodes, extraEdges };

      const byProject = new Map(); // project_id -> { name, buckets: Map(key -> {subjectId, name, items}) }
      for (const n of this.nodes) {
        if (!byProject.has(n.project_id)) byProject.set(n.project_id, { name: n.project_name, buckets: new Map() });
        const p = byProject.get(n.project_id);
        const key = `${n.project_id}:${n.subject_id || 'none'}`;
        if (!p.buckets.has(key)) p.buckets.set(key, { subjectId: n.subject_id || null, name: n.subject_id ? n.subject_name : 'Sem assunto', items: [] });
        p.buckets.get(key).items.push(n);
      }

      for (const [pid, p] of byProject) {
        const projectNodeId = `project:${pid}`;
        if (scope === 'graph') extraNodes.push({ id: projectNodeId, kind: 'project', label: p.name, project_id: pid });
        const hubId = scope === 'graph' ? projectNodeId : null;
        if (p.buckets.size >= 2) {
          for (const [key, b] of p.buckets) {
            const subjectNodeId = `subject:${key}`;
            extraNodes.push({ id: subjectNodeId, kind: 'subject', label: b.name, project_id: pid, subject_id: b.subjectId });
            if (hubId) extraEdges.push({ source: hubId, target: subjectNodeId, kind: 'hierarchy' });
            for (const item of b.items) extraEdges.push({ source: subjectNodeId, target: item.id, kind: 'hierarchy' });
          }
        } else if (hubId) {
          for (const [, b] of p.buckets) {
            for (const item of b.items) extraEdges.push({ source: hubId, target: item.id, kind: 'hierarchy' });
          }
        }
      }
      return { extraNodes, extraEdges };
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

      const { extraNodes, extraEdges } = this.hierarchyNodesAndEdges();
      const allNodes = [...this.nodes.map((n) => ({ ...n, kind: 'item' })), ...extraNodes];

      // Canvas cresce com o nº total de nós (itens + project/assunto) — zoom/pan (d3-zoom)
      // já dão conta de navegar num canvas maior que a tela. Múltiplo pequeno de propósito:
      // o espaçamento real quem resolve é o collide (abaixo), não um canvas enorme — canvas
      // grande demais só deixa tudo mais afastado visualmente, sem motivo.
      const side = Math.ceil(Math.sqrt(allNodes.length));
      this.width = Math.max(WIDTH, side * 48);
      this.height = Math.max(HEIGHT, side * 38);
      svg.setAttribute('viewBox', `0 0 ${this.width} ${this.height}`);
      while (svg.firstChild) svg.removeChild(svg.firstChild);

      const viewport = document.createElementNS(SVG_NS, 'g');
      viewport.setAttribute('class', 'graph-viewport');
      svg.appendChild(viewport);

      const allEdges = [...this.edges.map((e) => ({ ...e, kind: 'relation' })), ...extraEdges];
      const edgeEls = allEdges.map((e) => {
        const line = document.createElementNS(SVG_NS, 'line');
        line.setAttribute('class', this.edgeClass(e));
        viewport.appendChild(line);
        return line;
      });

      // Grau (nº de arestas de relação — não conta aresta de hierarquia) de cada item: raio
      // e espessura do nome acompanham, como no Obsidian — um hub muito conectado chama
      // mais atenção que uma folha solta. Project e assunto têm raio fixo (são sempre o
      // nível maior, não competem por destaque com os itens).
      const degree = new Map(this.nodes.map((n) => [n.id, 0]));
      for (const e of this.edges) {
        degree.set(e.source, (degree.get(e.source) || 0) + 1);
        degree.set(e.target, (degree.get(e.target) || 0) + 1);
      }
      const radius = (n) => {
        if (n.kind === 'project') return RADIUS.project;
        if (n.kind === 'subject') return RADIUS.subject;
        return Math.min(16, 4 + Math.sqrt(degree.get(n.id) || 0) * 2.2);
      };

      // Nó (forma) e rótulo (texto) são DOIS elementos separados, em duas camadas: todas as
      // formas primeiro, todos os rótulos depois — assim, não importa quão perto dois nós
      // fiquem, uma forma nunca pinta por cima do texto de outro nó (só uma aresta pode:
      // regra do usuário, "a única coisa que pode sobrepor são as arestas"). Continuam
      // arrastáveis e clicáveis juntos: cada rótulo guarda uma referência pro seu <g> de
      // forma, e os dois recebem o mesmo translate a cada tick.
      const nodeEls = allNodes.map((n) => {
        const g = document.createElementNS(SVG_NS, 'g');
        g.setAttribute('class', this.nodeClass(n));
        const r = radius(n);
        const title = document.createElementNS(SVG_NS, 'title');
        title.textContent = n.label || n.title;

        let shape;
        if (n.kind === 'project') {
          shape = document.createElementNS(SVG_NS, 'rect');
          shape.setAttribute('x', String(-r));
          shape.setAttribute('y', String(-r));
          shape.setAttribute('width', String(r * 2));
          shape.setAttribute('height', String(r * 2));
          shape.setAttribute('rx', '4');
        } else if (n.kind === 'subject') {
          shape = document.createElementNS(SVG_NS, 'polygon');
          shape.setAttribute('points', `0,${-r} ${r},${r} ${-r},${r}`);
        } else {
          shape = document.createElementNS(SVG_NS, 'circle');
          shape.setAttribute('r', String(r));
        }
        if (n.kind === 'project') {
          shape.setAttribute('fill', `hsl(${hueOf(n.project_id)}, 55%, 52%)`);
        } else if (n.kind === 'subject') {
          const l = 36 + (hueOf(n.id) % 40);
          shape.setAttribute('fill', `hsl(${hueOf(n.project_id)}, 55%, ${l}%)`);
        }
        g.append(title, shape);
        viewport.appendChild(g);
        return g;
      });

      const labelEls = allNodes.map((n) => {
        const r = radius(n);
        const text = document.createElementNS(SVG_NS, 'text');
        text.setAttribute('class', n.kind === 'item' ? 'glabel' : `glabel glabel-${n.kind}`);
        text.setAttribute('x', String(r + 4));
        text.setAttribute('y', '4');
        text.textContent = this.label(n.label || n.title);
        viewport.appendChild(text);
        return text;
      });

      nodeEls.forEach((g, i) => {
        const label = labelEls[i];
        g.addEventListener('pointerenter', () => {
          g.classList.add('hover');
          label.classList.add('hover');
        });
        g.addEventListener('pointerleave', () => {
          g.classList.remove('hover');
          label.classList.remove('hover');
        });
      });

      const byId = new Map(allNodes.map((n) => [n.id, n]));
      const links = allEdges
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
        allNodes.forEach((n, i) => {
          const t = `translate(${n.x},${n.y})`;
          nodeEls[i].setAttribute('transform', t);
          labelEls[i].setAttribute('transform', t);
        });
      };

      // Nada de grade nominal nem força de agrupamento à parte: project e assunto são nós
      // como qualquer outro, e a aresta de hierarquia (link, mais curta e mais forte que a
      // de relação) já faz a física clusterizar os itens em torno do próprio hub sozinha —
      // é a física de um grafo comum, só que com nós de tamanho/forma diferentes. Distância
      // e carga baixas de propósito: o grupo tem que ficar coeso, não espalhado pelo canvas
      // — quem evita uma forma cobrir o texto de outro nó é a ordem de desenho (rótulo
      // sempre por cima, ver labelEls abaixo), não a distância entre eles.
      this.sim = forceSimulation(allNodes)
        .force('charge', forceManyBody().strength((n) => (n.kind === 'item' ? -70 : -150)))
        .force(
          'link',
          forceLink(links)
            .distance((l) => (l.kind === 'hierarchy' ? 36 : 55))
            .strength((l) => (l.kind === 'hierarchy' ? 0.85 : 0.4)),
        )
        .force('center', forceCenter(this.width / 2, this.height / 2))
        .force('collide', forceCollide((n) => radius(n) + 6))
        .on('tick', tick);

      // Deixa o layout assentar de uma vez antes do primeiro desenho: o timer do d3 usa
      // requestAnimationFrame, que o navegador pausa se a aba abrir em segundo plano — sem
      // isso, o grafo ficaria com todos os nós empilhados até alguém olhar pra aba.
      this.sim.stop();
      for (let i = 0; i < 150; i++) this.sim.tick();
      tick();
      this.sim.stop();

      // Clique abre item/project/assunto; arrastar não deve contar como clique (d3-drag não
      // distingue, então só navega se o nó não se mexeu entre mousedown e mouseup).
      nodeEls.forEach((g, i) => {
        const n = allNodes[i];
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
