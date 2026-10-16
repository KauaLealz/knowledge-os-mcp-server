// Markdown -> HTML seguro: marked -> DOMPurify -> highlight.js. O conteúdo vem da API e é
// tratado como não confiável: nada chega ao DOM sem passar por DOMPurify.sanitize.
// Extras: KaTeX (math), blocos ```mermaid viram diagramas (carregados sob demanda) e
// listas de tarefas mantêm o checkbox. O mermaid acompanha o tema claro/escuro.
import { marked } from '../vendor/marked.esm.js';
import DOMPurify from '../vendor/purify.esm.js';
import hljs from '../vendor/highlight.esm.js';
import markedKatex from '../vendor/marked-katex.esm.js';

marked.use({ gfm: true, breaks: true });
// KaTeX: $...$ na linha, $$...$$ em bloco. output:'html' evita MathML — basta liberar o
// atributo `style` no sanitizador (o KaTeX usa style para posicionar os glifos).
marked.use(markedKatex({ throwOnError: false, nonStandard: true, output: 'html' }));

// Conteúdo não confiável. Diferenças para o perfil padrão do DOMPurify: `input` é permitido
// (mas reduzido a checkbox desabilitado, abaixo) para a lista de tarefas, e `style` continua
// liberado (o KaTeX precisa). Seguem barrados script/on*/form e afins.
const CONTENT_OPTS = {
  RETURN_DOM_FRAGMENT: true,
  FORBID_TAGS: ['style', 'form', 'textarea', 'select', 'button'],
  FORBID_ATTR: ['action', 'formaction'],
};

// SVG do mermaid (gerado pelo nosso render, securityLevel 'strict'): perfil SVG + o <style>
// que o próprio mermaid embute. Devolve string para innerHTML.
const SVG_OPTS = {
  USE_PROFILES: { svg: true, svgFilters: true },
  ADD_TAGS: ['style'],
  ADD_ATTR: ['style'],
};

function slugify(text) {
  return (
    text
      .toLowerCase()
      .normalize('NFD')
      .replace(/[̀-ͯ]/g, '')
      .replace(/[^a-z0-9]+/g, '-')
      .replace(/^-+|-+$/g, '') || 'secao'
  );
}

/** Renderiza Markdown em um DocumentFragment sanitizado e devolve os H2/H3 para a TOC.
 *  Blocos ```mermaid ficam marcados como pendentes; quem renderiza é renderMermaid (async). */
export function render(src) {
  const dirty = marked.parse(src || '', { async: false });
  const fragment = DOMPurify.sanitize(dirty, CONTENT_OPTS);

  const headings = [];
  const used = new Set();
  for (const h of fragment.querySelectorAll('h1, h2, h3, h4')) {
    let id = slugify(h.textContent);
    let n = 2;
    while (used.has(id)) id = `${slugify(h.textContent)}-${n++}`;
    used.add(id);
    h.id = id;
    if (h.tagName === 'H2' || h.tagName === 'H3') {
      headings.push({ id, text: h.textContent, level: h.tagName === 'H2' ? 2 : 3 });
    }
  }

  for (const a of fragment.querySelectorAll('a[href]')) {
    if (/^https?:/i.test(a.getAttribute('href'))) {
      a.setAttribute('target', '_blank');
      a.setAttribute('rel', 'noopener noreferrer');
    }
  }
  for (const img of fragment.querySelectorAll('img')) img.setAttribute('loading', 'lazy');

  // Lista de tarefas: mantém só checkbox e sempre desabilitado (conteúdo é leitura).
  for (const inp of fragment.querySelectorAll('input')) {
    if (inp.getAttribute('type') !== 'checkbox') {
      inp.remove();
      continue;
    }
    inp.setAttribute('disabled', '');
  }

  for (const code of fragment.querySelectorAll('pre code')) {
    const m = /language-([\w+-]+)/.exec(code.className);
    if (m && m[1] === 'mermaid') {
      // Não passa pelo highlight: vira diagrama depois (renderMermaid). O texto fica de
      // fallback (mostrado se o mermaid falhar ou enquanto carrega).
      const pre = code.parentElement;
      pre.classList.add('mermaid-pending');
      pre.dataset.mermaid = '1';
      continue;
    }
    const lang = m && hljs.getLanguage(m[1]) ? m[1] : null;
    if (lang) {
      code.className = `hljs language-${lang}`;
      code.parentElement.dataset.lang = lang;
      hljs.highlightElement(code);
    } else {
      code.className = 'hljs';
      if (m) code.parentElement.dataset.lang = m[1];
    }
  }
  return { fragment, headings };
}

/** Renderiza dentro de um elemento e devolve os headings. Dispara o mermaid em seguida. */
export function renderTo(el, src) {
  const { fragment, headings } = render(src);
  el.replaceChildren(fragment);
  renderMermaid(el);
  return headings;
}

// ---- Mermaid (carregado sob demanda) ----

let mermaidMod = null;
let mermaidSeq = 0;

async function getMermaid() {
  if (!mermaidMod) {
    mermaidMod = (await import('../vendor/mermaid.esm.js')).default;
  }
  return mermaidMod;
}

// Config comum. suppressErrorRendering: em erro o mermaid NÃO injeta o diagrama-bomba de
// "Syntax error" no documento — quem trata o erro é drawInto (mantém o código com aviso).
function initMermaid(mermaid) {
  mermaid.initialize({
    startOnLoad: false,
    securityLevel: 'strict',
    suppressErrorRendering: true,
    theme: mermaidTheme(),
  });
}

function mermaidTheme() {
  const set = document.documentElement.getAttribute('data-theme');
  if (set === 'dark') return 'dark';
  if (set === 'light') return 'default';
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'default';
}

async function drawInto(mermaid, target, source) {
  const id = `mmd-${++mermaidSeq}`;
  try {
    const { svg, bindFunctions } = await mermaid.render(id, source);
    const box = document.createElement('div');
    box.className = 'mermaid-diagram';
    box.dataset.mermaidSrc = source;
    box.innerHTML = DOMPurify.sanitize(svg, SVG_OPTS);
    bindFunctions?.(box);
    target.replaceWith(box);
    return box;
  } catch {
    // Erro de sintaxe: mantém o código visível, com um aviso. Não quebra a página.
    // Limpa qualquer nó de medição que o mermaid tenha deixado órfão.
    document.getElementById(id)?.remove();
    document.getElementById(`d${id}`)?.remove();
    if (target.classList?.contains('mermaid-pending')) {
      target.classList.remove('mermaid-pending');
      target.classList.add('mermaid-error');
    }
    return null;
  }
}

/** Renderiza todos os blocos ```mermaid pendentes dentro de `root`. */
export async function renderMermaid(root) {
  const pending = root.querySelectorAll('pre[data-mermaid]');
  if (!pending.length) return;
  ensureThemeObserver();
  const mermaid = await getMermaid();
  initMermaid(mermaid);
  for (const pre of pending) {
    const source = (pre.querySelector('code') || pre).textContent;
    await drawInto(mermaid, pre, source);
  }
}

// Re-renderiza os diagramas já desenhados quando o tema muda (atributo data-theme ou o tema
// do sistema). Mantém o código-fonte em data-mermaid-src para poder redesenhar.
let themeObserver = null;

async function rerenderAllMermaid() {
  const boxes = document.querySelectorAll('.mermaid-diagram[data-mermaid-src]');
  if (!boxes.length) return;
  const mermaid = await getMermaid();
  initMermaid(mermaid);
  for (const box of boxes) {
    await drawInto(mermaid, box, box.dataset.mermaidSrc);
  }
}

function ensureThemeObserver() {
  if (themeObserver) return;
  themeObserver = new MutationObserver(rerenderAllMermaid);
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ['data-theme'],
  });
  window
    .matchMedia('(prefers-color-scheme: dark)')
    .addEventListener?.('change', rerenderAllMermaid);
}
