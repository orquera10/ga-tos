{% load static %}
const CACHE_NAME = 'gastos-pwa-{{ app_version|default:"dev" }}';
const STATIC_ASSETS = [
  "{% url 'presupuestos:index' %}",
  "{% static 'presupuestos/css/styles.css' %}?v={{ app_version|default:"dev" }}",
  "{% static 'presupuestos/img/logoGa$tos.png' %}?v={{ app_version|default:"dev" }}",
  "{% static 'presupuestos/img/icons/icon-192.png' %}?v={{ app_version|default:"dev" }}",
  "{% static 'presupuestos/img/icons/icon-512.png' %}?v={{ app_version|default:"dev" }}",
  "{% static 'presupuestos/manifest.json' %}?v={{ app_version|default:"dev" }}"
];

self.addEventListener('install', function(event) {
  event.waitUntil(
    caches.open(CACHE_NAME).then(function(cache) {
      return cache.addAll(STATIC_ASSETS);
    })
  );
  self.skipWaiting();
});

self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(key) {
          return key !== CACHE_NAME;
        }).map(function(key) {
          return caches.delete(key);
        })
      );
    })
  );
  self.clients.claim();
});

self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') {
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request).catch(function() {
        return caches.match("{% url 'presupuestos:index' %}");
      })
    );
    return;
  }

  var requestUrl = new URL(event.request.url);
  if (requestUrl.origin === self.location.origin && requestUrl.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(function(cachedResponse) {
        return cachedResponse || fetch(event.request).then(function(response) {
          var responseCopy = response.clone();
          caches.open(CACHE_NAME).then(function(cache) {
            cache.put(event.request, responseCopy);
          });
          return response;
        });
      })
    );
  }
});
