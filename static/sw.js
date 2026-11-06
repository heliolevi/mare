// Service worker mínimo: guarda o "casco" do app para abrir offline. Dados da API nunca são guardados.
const VERSAO = 'v6';
const CASCO = `mare-casco-${VERSAO}`;
const ARQUIVOS = [
  '/', '/index.html', '/manifest.webmanifest',
  '/css/tokens.css', '/css/app.css',
  '/dist/main.js',
  '/fonts/lexend-exa-latin-500-normal.woff2', '/fonts/manrope-latin-wght-normal.woff2', '/fonts/jetbrains-mono-latin-wght-normal.woff2',
  '/icons/icon-192.png', '/logo/favicon.svg',
];

self.addEventListener('install', (e) => {
  e.waitUntil(caches.open(CASCO).then((c) => c.addAll(ARQUIVOS)).then(() => self.skipWaiting()));
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((chaves) => Promise.all(chaves.filter((k) => k.startsWith('mare-casco-') && k !== CASCO).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()));
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  const url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  // Rede primeiro: o app sempre mostra a versão mais nova; o cache só cobre a falta de conexão.
  e.respondWith(
    fetch(req)
      .then((res) => {
        if (res.ok) { const copia = res.clone(); caches.open(CASCO).then((c) => c.put(req, copia)); }
        return res;
      })
      .catch(() => caches.match(req).then((r) => r || caches.match('/index.html'))));
});
