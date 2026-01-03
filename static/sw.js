const CACHE_NAME = 'messenger-v1';
const urlsToCache = [
    '/',
    '/static/css/style.css',
    '/static/js/app.js',
    '/manifest.json'
];

// Установка Service Worker
self.addEventListener('install', event => {
    event.waitUntil(
        caches.open(CACHE_NAME)
            .then(cache => {
                console.log('Кэширование файлов');
                return cache.addAll(urlsToCache);
            })
    );
});

// Активация и очистка старых кэшей
self.addEventListener('activate', event => {
    event.waitUntil(
        caches.keys().then(cacheNames => {
            return Promise.all(
                cacheNames.map(cacheName => {
                    if (cacheName !== CACHE_NAME) {
                        console.log('Удаление старого кэша:', cacheName);
                        return caches.delete(cacheName);
                    }
                })
            );
        })
    );
});

// Обработка запросов
self.addEventListener('fetch', event => {
    // Пропускаем запросы к API и WebSocket
    if (event.request.url.includes('/api/') || 
        event.request.url.includes('/socket.io/')) {
        return;
    }
    
    event.respondWith(
        caches.match(event.request)
            .then(response => {
                // Возвращаем из кэша или делаем сетевой запрос
                return response || fetch(event.request);
            })
    );
});

// Получение push-уведомлений
self.addEventListener('push', event => {
    const data = event.data ? event.data.json() : {};
    
    const title = data.title || 'Messenger';
    const options = {
        body: data.body || 'Новое уведомление',
        icon: '/static/icon.png',
        badge: '/static/badge.png',
        tag: 'messenger-notification',
        data: data.url || '/'
    };
    
    event.waitUntil(
        self.registration.showNotification(title, options)
    );
});

// Обработка кликов по уведомлениям
self.addEventListener('notificationclick', event => {
    event.notification.close();
    
    event.waitUntil(
        clients.matchAll({ type: 'window', includeUncontrolled: true })
            .then(clientList => {
                // Если есть открытое окно, фокусируемся на нем
                for (const client of clientList) {
                    if (client.url === event.notification.data) {
                        return client.focus();
                    }
                }
                
                // Иначе открываем новое окно
                if (clients.openWindow) {
                    return clients.openWindow(event.notification.data);
                }
            })
    );
});