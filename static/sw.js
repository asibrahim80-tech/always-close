// ═══════════════════════════════════════════════════════════════
// Always Close — Service Worker (Offline Fallback)
// ═══════════════════════════════════════════════════════════════
const CACHE_NAME  = 'ac-offline-v1';
const OFFLINE_URL = '/static/offline.html';

// ── Install: cache the offline page ──────────────────────────
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_NAME).then(cache => {
      return cache.add(new Request(OFFLINE_URL, { cache: 'reload' }));
    })
  );
  self.skipWaiting();
});

// ── Activate: clean old caches ────────────────────────────────
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(keys.filter(k => k !== CACHE_NAME).map(k => caches.delete(k)))
    )
  );
  self.clients.claim();
});

// ── Fetch: intercept navigation failures ─────────────────────
self.addEventListener('fetch', event => {
  // Only intercept GET navigation requests (page loads)
  if (event.request.method !== 'GET') return;
  if (event.request.headers.get('Accept') &&
      !event.request.headers.get('Accept').includes('text/html')) return;

  const url = new URL(event.request.url);

  // Skip cross-origin requests (CDN, external assets, Telegram)
  if (url.origin !== self.location.origin) return;

  // Skip API calls — only intercept page navigations
  if (url.pathname.startsWith('/api/')) return;
  if (url.pathname.startsWith('/static/')) return;

  event.respondWith(
    fetch(event.request)
      .then(response => {
        // If server returned an error page, pass it through
        return response;
      })
      .catch(() => {
        // Network failure — server is unreachable
        // Preserve lang param for the offline page
        return caches.match(OFFLINE_URL).then(cached => {
          if (cached) return cached;
          // Fallback if cache miss
          return new Response(
            '<html><body style="font-family:sans-serif;display:flex;align-items:center;justify-content:center;height:100vh;background:#0f0c29;color:#fff;text-align:center"><div><h2>📡 Always Close</h2><p>انقطع الاتصال — Connection Lost</p></div></body></html>',
            { headers: { 'Content-Type': 'text/html; charset=UTF-8' } }
          );
        });
      })
  );
});
