// Markdown -> HTML seguro: marked -> DOMPurify -> highlight.js. O conteúdo vem da API e é
// tratado como não confiável: nada chega ao DOM sem passar por DOMPurify.sanitize.
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import hljs from 'highlight.js';

marked.use({ gfm: true, breaks: false });

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

/** Renderiza Markdown em um DocumentFragment sanitizado e devolve os H2/H3 para a TOC. */
export function render(src) {
  const dirty = marked.parse(src || '', { async: false });
  const fragment = DOMPurify.sanitize(dirty, {
    RETURN_DOM_FRAGMENT: true,
    FORBID_TAGS: ['style', 'form', 'input', 'button', 'textarea', 'select'],
    FORBID_ATTR: ['style', 'action', 'formaction'],
  });

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

  for (const code of fragment.querySelectorAll('pre code')) {
    const m = /language-([\w+-]+)/.exec(code.className);
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

/** Renderiza dentro de um elemento e devolve os headings. */
export function renderTo(el, src) {
  const { fragment, headings } = render(src);
  el.replaceChildren(fragment);
  return headings;
}
