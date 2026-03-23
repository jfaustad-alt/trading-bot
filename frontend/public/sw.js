// Service Worker — enables PWA "install to home screen" functionality.
// This is a minimal service worker that caches the app shell for offline use.

const CACHE_NAME = 'tradingbot-v1'

self.addEventListener('install', (event) => {
  self.skipWaiting()
})

self.addEventListener('activate', (event) => {
  event.waitUntil(clients.claim())
})

self.addEventListener('fetch', (event) => {
  // For API calls, always go to the network (we want live data).
  if (event.request.url.includes('/api/')) {
    return
  }

  // For app shell files, try network first, fall back to cache.
  event.respondWith(
    fetch(event.request)
      .then((response) => {
        const clone = response.clone()
        caches.open(CACHE_NAME).then((cache) => cache.put(event.request, clone))
        return response
      })
      .catch(() => caches.match(event.request))
  )
})
