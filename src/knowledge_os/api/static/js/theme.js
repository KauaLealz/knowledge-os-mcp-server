// Aplica o tema antes do primeiro paint (sem flash). Funciona sem storage.
(function () {
  try {
    var t = localStorage.getItem('kos.theme');
    if (t === 'light' || t === 'dark') document.documentElement.setAttribute('data-theme', t);
  } catch (e) {}
})();
