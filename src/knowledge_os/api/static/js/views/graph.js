// Grafo de relações (workspace, project ou subject — a rota decide o escopo). Física de
// layout via d3-force, pan/zoom via d3-zoom, arrastar nó via d3-drag (bundles vendorizados
// em vendor/, sem CDN em runtime). DOM sempre via createElementNS/setAttribute — nunca
// atribuição direta de marcação bruta (x-html), mesma regra do resto do app (markdown.js é
// a única exceção, com DOMPurify).
//
// Project/assunto não viram texto flutuando perto dos nós (tentamos isso antes: a física
// pode arrastar um grupo pequeno pra longe de onde o rótulo nominal ficaria, e o texto
// descolava do que nomeava). Em vez disso: um contorno desenhado DEPOIS que a simulação
// assenta, ao redor de onde os nós daquele grupo realmente pararam (sempre abraça a
// posição real, nunca descola) — e o nome de cada cor/contorno mora numa legenda fixa
// acima do SVG (HTML comum, fora da física: nunca comprime, nunca sobrepõe).
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
// Tamanho mínimo de célula por project na grade do workspace: espaço de verdade pro
// contorno do project e os sub-grupos de assunto não ficarem espremidos. Com mais
// projects, o canvas cresce (zoom e pan já dão conta de navegar nele).
const PROJECT_CELL_W = 340;
const PROJECT_CELL_H = 260;

/** Hash determinístico de um id pra um matiz (0-359) — mesmo id sempre a mesma cor,
 * entre recarregamentos e entre o SVG e a legenda. */
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

    /** Mapas de cor/nome por project e por assunto, únicos pros dois usos que precisam
     * concordar entre si: a legenda (HTML, estática) e o contorno desenhado no SVG. Um
     * assunto só entra no mapa quando o project dele tem 2+ (mesma regra de quando o
     * sub-agrupamento entra no layout, ver groupCenters). */
    colorMaps() {
      const projectHue = new Map();
      const projectName = new Map();
      const subjectHue = new Map(); // key `${project_id}:${subject_id||'none'}` -> {h, l}
      const subjectName = new Map();
      const byProject = new Map(); // project_id -> Map(key -> nome)
      for (const n of this.nodes) {
        if (!projectHue.has(n.project_id)) {
          projectHue.set(n.project_id, hueOf(n.project_id));
          projectName.set(n.project_id, n.project_name);
        }
        const key = `${n.project_id}:${n.subject_id || 'none'}`;
        if (!byProject.has(n.project_id)) byProject.set(n.project_id, new Map());
        if (!byProject.get(n.project_id).has(key)) {
          byProject.get(n.project_id).set(key, n.subject_id ? n.subject_name : 'Sem assunto');
        }
      }
      for (const [pid, bykey] of byProject) {
        if (bykey.size < 2) continue;
        const h = hueOf(pid);
        let i = 0;
        for (const [key, name] of bykey) {
          subjectHue.set(key, { h, l: 38 + ((i * 15) % 45) });
          subjectName.set(key, name);
          i++;
        }
      }
      return { projectHue, projectName, subjectHue, subjectName };
    },

    /** Legenda de projects — só faz sentido com 2+ (grafo do workspace); um project só
     * já está no breadcrumb. */
    get legendProjects() {
      if (this.app.route.name !== 'graph') return [];
      const { projectHue, projectName } = this.colorMaps();
      if (projectHue.size < 2) return [];
      return [...projectHue].map(([id, h]) => ({ id, name: projectName.get(id), color: `hsl(${h}, 62%, 58%)` }));
    },

    get legendSubjects() {
      const scope = this.app.route.name;
      if (scope !== 'graph' && scope !== 'project-graph') return [];
      const { subjectHue, subjectName } = this.colorMaps();
      return [...subjectHue].map(([key, { h, l }]) => ({ id: key, name: subjectName.get(key), color: `hsl(${h}, 55%, ${l}%)` }));
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

      // Agrupamento em duas camadas: no grafo do workspace, cada project puxa os próprios
      // nós pra uma região da grade; dentro dela, os assuntos daquele project (mais um
      // balde "Sem assunto" pros itens soltos) puxam pra sub-regiões. No grafo de um
      // project só, não existe nível de project (seria redundante) — vai direto pro nível
      // de assunto, usando o canvas inteiro como região única. No grafo de um assunto,
      // nada disso entra: já é um grupo só. É só um alvo de força (fraco — o grupo pode
      // se espalhar além dele): o contorno visual é desenhado depois, ao redor de onde os
      // nós realmente pararam, nunca da célula nominal.
      const scope = this.app.route.name;
      const projectKey = (n) => n.project_id;
      const subjectKey = (n) => `${n.project_id}:${n.subject_id || 'none'}`;

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
      // (fração da região) deixando um respiro visível entre clusters vizinhos.
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

      // Força fraca pro centro do project e, por cima, uma força um pouco mais forte pro
      // centro do sub-grupo de assunto — o resultado é o aninhamento: o assunto puxa mais,
      // mas o project continua por perto. Propositalmente fracas (não uma gaiola rígida):
      // a repulsão entre nós (charge) ganha espaço pra espalhar o grupo, e o contorno
      // visual (desenhado depois de assentar) é que vai abraçar onde eles pararam de
      // verdade — não depende de ninguém ficar exatamente no alvo.
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

      // Contorno de cada grupo — desenhado DEPOIS que os nós assentaram, ao redor de onde
      // eles realmente pararam (bounding box + folga), nunca da célula nominal da grade.
      // É isso que garante que o contorno nunca descola do que ele cerca, mesmo quando a
      // física espalha um grupo pequeno pra mais longe do alvo do que o esperado. Entram
      // ANTES de nós e linhas no DOM (pintura em ordem de documento): ficam por trás,
      // como um fundo, nunca cobrindo um nó.
      const bbox = (ns) => {
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
        for (const n of ns) {
          if (n.x < minX) minX = n.x;
          if (n.x > maxX) maxX = n.x;
          if (n.y < minY) minY = n.y;
          if (n.y > maxY) maxY = n.y;
        }
        return { minX, maxX, minY, maxY };
      };
      const addShape = (cls, ns, hue, light, pad, rx) => {
        if (ns.length < 2) return; // um nó só não forma "grupo" visível — contorno em cima dele seria só ruído
        const { minX, maxX, minY, maxY } = bbox(ns);
        const rect = document.createElementNS(SVG_NS, 'rect');
        rect.setAttribute('class', cls);
        rect.setAttribute('x', String(minX - pad));
        rect.setAttribute('y', String(minY - pad));
        rect.setAttribute('width', String(maxX - minX + pad * 2));
        rect.setAttribute('height', String(maxY - minY + pad * 2));
        rect.setAttribute('rx', String(rx));
        rect.setAttribute('stroke', `hsl(${hue}, 62%, ${light}%)`);
        rect.setAttribute('fill', `hsla(${hue}, 62%, ${light}%, 0.07)`);
        viewport.insertBefore(rect, viewport.firstChild);
      };

      const { projectHue, subjectHue } = this.colorMaps();
      if (projectCenters) {
        for (const id of projectIds) {
          const ns = this.nodes.filter((n) => projectKey(n) === id);
          addShape('gshape gshape-planet', ns, projectHue.get(id), 58, 26, 20);
        }
      }
      if (subjectCenters) {
        for (const k of subjectCenters.keys()) {
          const ns = this.nodes.filter((n) => subjectKey(n) === k);
          const { h, l } = subjectHue.get(k) || { h: 0, l: 50 };
          addShape('gshape gshape-country', ns, h, l, 16, 12);
        }
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
