// Guarda só a "casca" do app para abrir rápido. Vídeo e dados sempre vêm ao vivo do servidor.
const CACHE = "cameras-v1";
const ARQUIVOS = ["./", "index.html", "estilo.css", "app.js", "icone.svg", "manifest.json", "chart.umd.js"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll(ARQUIVOS)));
  self.skipWaiting();
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k)))));
  self.clients.claim();
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.pathname.includes("/api/")) return;
  // tenta a rede primeiro (versão nova), se falhar usa o cache
  e.respondWith(
    fetch(e.request)
      .then((r) => { if (url.origin === location.origin) caches.open(CACHE).then((c) => c.put(e.request, r.clone())); return r; })
      .catch(() => caches.match(e.request))
  );
});
