// Douala Power Alert Service Worker (v2)
// Offline Fallback, Dynamic Caching & Push Notifications

const CACHE_NAME = 'douala-power-cache-v2';
const STATIC_PRECACHE = [
    '/',
    '/offline',
    '/static/css/style.css',
    '/static/js/script.js',
    '/static/manifest.json',
    '/static/img/icon-bolt.svg',
    '/static/img/icon-192.png',
    '/static/img/icon-512.png'
];

// 1. Install & Pre-cache Essential Shell
self.addEventListener('install', (event) => {
    event.waitUntil(
        caches.open(CACHE_NAME).then((cache) => {
            return cache.addAll(STATIC_PRECACHE);
        }).then(() => self.skipWaiting())
    );
});

// 2. Activate & Purge Stale Caches
self.addEventListener('activate', (event) => {
    event.waitUntil(
        caches.keys().then((keys) => {
            return Promise.all(
                keys.map((key) => {
                    if (key !== CACHE_NAME) {
                        return caches.delete(key);
                    }
                })
            );
        }).then(() => self.clients.claim())
    );
});

// 3. Fetch Strategy: Network-First with Offline Fallback
self.addEventListener('fetch', (event) => {
    const req = event.request;

    // Only handle GET requests
    if (req.method !== 'GET') return;

    // A. Page Navigations: Network First -> Fallback to /offline
    if (req.mode === 'navigate') {
        event.respondWith(
            fetch(req)
                .then((networkRes) => {
                    if (networkRes && networkRes.status === 200) {
                        const copy = networkRes.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
                    }
                    return networkRes;
                })
                .catch(() => {
                    return caches.match(req).then((cached) => {
                        return cached || caches.match('/offline');
                    });
                })
        );
        return;
    }

    // B. Static Assets: Cache First with Network Fallback & Revalidate
    if (req.url.includes('/static/')) {
        event.respondWith(
            caches.match(req).then((cached) => {
                const fetchPromise = fetch(req).then((networkRes) => {
                    if (networkRes && networkRes.status === 200) {
                        const copy = networkRes.clone();
                        caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
                    }
                    return networkRes;
                }).catch(() => cached);

                return cached || fetchPromise;
            })
        );
        return;
    }

    // C. Default: Network with Cache Fallback
    event.respondWith(
        fetch(req)
            .then((networkRes) => {
                if (networkRes && networkRes.status === 200 && req.url.includes('/api/')) {
                    const copy = networkRes.clone();
                    caches.open(CACHE_NAME).then((cache) => cache.put(req, copy));
                }
                return networkRes;
            })
            .catch(() => caches.match(req))
    );
});

// 4. Notification Click Action
self.addEventListener('notificationclick', (event) => {
    event.notification.close();
    const targetUrl = event.notification.data?.url || '/outages';

    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true }).then((clientList) => {
            for (const client of clientList) {
                if ('focus' in client) {
                    client.navigate(targetUrl);
                    return client.focus();
                }
            }
            if (clients.openWindow) {
                return clients.openWindow(targetUrl);
            }
        })
    );
});
