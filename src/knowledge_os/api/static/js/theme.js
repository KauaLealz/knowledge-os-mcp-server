// Aplica o tema antes do primeiro paint (sem flash). Funciona sem storage.
// Só há claro e escuro: sem escolha salva, vale o tema do sistema (prefers-color-scheme).
(function () {
  try {
    var t = localStorage.getItem('kos.theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
    else if (t) localStorage.removeItem('kos.theme'); // valor antigo ("system")
  } catch (e) {}
})();
