{% load static %}
const CACHE_NAME = 'gastos-pwa-v1';
const STATIC_ASSETS = [
  "{% url 'presupuestos:index' %}",
  "{% static 'presupuestos/css/styles.css' %}",
  "{% static 'presupuestos/img/logoGa$tos.png' %}",
  "{% static 'presupuestos/img/icons/icon-192.png' %}",
  "{% static 'presupuestos/img/icons/icon-512.png' %}",
  "{% static 'presupuestos/manifest.json' %}"
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

  event.respondWith(
    fetch(event.request)
      .then(function(response) {
        var responseCopy = response.clone();
        caches.open(CACHE_NAME).then(function(cache) {
          cache.put(event.request, responseCopy);
        });
        return response;
      })
      .catch(function() {
        return caches.match(event.request).then(function(cachedResponse) {
          return cachedResponse || caches.match("{% url 'presupuestos:index' %}");
        });
      })
  );
});
