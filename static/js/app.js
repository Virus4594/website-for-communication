// Основной файл JavaScript для приложения

// Инициализация при загрузке страницы
document.addEventListener('DOMContentLoaded', function() {
    console.log('Messenger application loaded');
    
    // Инициализация Service Worker
    initServiceWorker();
    
    // Инициализация уведомлений
    initNotifications();
    
    // Инициализация темной темы
    initDarkMode();
    
    // Проверка авторизации для защищенных страниц
    checkAuth();
});

// Service Worker
function initServiceWorker() {
    if ('serviceWorker' in navigator) {
        navigator.serviceWorker.register('/static/sw.js')
            .then(registration => {
                console.log('Service Worker зарегистрирован:', registration);
            })
            .catch(error => {
                console.log('Ошибка регистрации Service Worker:', error);
            });
    }
}

// Уведомления
function initNotifications() {
    if ('Notification' in window && Notification.permission === 'default') {
        Notification.requestPermission().then(permission => {
            console.log('Разрешение уведомлений:', permission);
        });
    }
}

// Темная тема
function initDarkMode() {
    const darkMode = localStorage.getItem('darkMode') === 'true';
    if (darkMode) {
        document.body.classList.add('dark-mode');
    }
}

// Проверка авторизации
function checkAuth() {
    const protectedPaths = ['/messages', '/friends', '/profile', '/settings'];
    const currentPath = window.location.pathname;
    
    if (protectedPaths.some(path => currentPath.startsWith(path))) {
        // Если на защищенной странице, проверяем наличие токена
        const csrfToken = document.querySelector('meta[name="csrf-token"]');
        if (!csrfToken) {
            console.warn('CSRF токен не найден');
        }
    }
}

// Всплывающие уведомления
function showToast(message, type = 'info', duration = 5000) {
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.textContent = message;
    toast.style.cssText = `
        position: fixed;
        top: 20px;
        right: 20px;
        padding: 15px 20px;
        background: ${type === 'success' ? '#28a745' : type === 'error' ? '#dc3545' : '#17a2b8'};
        color: white;
        border-radius: 5px;
        z-index: 10000;
        animation: slideIn 0.3s ease;
    `;
    
    document.body.appendChild(toast);
    
    setTimeout(() => {
        toast.style.animation = 'slideOut 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, duration);
    
    // Добавляем стили для анимации
    if (!document.querySelector('#toast-styles')) {
        const style = document.createElement('style');
        style.id = 'toast-styles';
        style.textContent = `
            @keyframes slideIn {
                from { transform: translateX(100%); opacity: 0; }
                to { transform: translateX(0); opacity: 1; }
            }
            @keyframes slideOut {
                from { transform: translateX(0); opacity: 1; }
                to { transform: translateX(100%); opacity: 0; }
            }
        `;
        document.head.appendChild(style);
    }
}

// Форматирование даты
function formatDate(dateString) {
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    
    // Если меньше минуты
    if (diff < 60000) {
        return 'только что';
    }
    
    // Если меньше часа
    if (diff < 3600000) {
        const minutes = Math.floor(diff / 60000);
        return `${minutes} ${pluralize(minutes, ['минуту', 'минуты', 'минут'])} назад`;
    }
    
    // Если сегодня
    if (date.toDateString() === now.toDateString()) {
        return `сегодня в ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
    }
    
    // Если вчера
    const yesterday = new Date(now);
    yesterday.setDate(yesterday.getDate() - 1);
    if (date.toDateString() === yesterday.toDateString()) {
        return `вчера в ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
    }
    
    // Старше
    return `${date.toLocaleDateString()} в ${date.toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})}`;
}

// Склонение слов
function pluralize(number, words) {
    const cases = [2, 0, 1, 1, 1, 2];
    return words[(number % 100 > 4 && number % 100 < 20) ? 2 : cases[(number % 10 < 5) ? number % 10 : 5]];
}

// Экранирование HTML
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Загрузка файлов
function uploadFile(file, endpoint) {
    return new Promise((resolve, reject) => {
        const formData = new FormData();
        formData.append('file', file);
        
        const csrfToken = document.querySelector('meta[name="csrf-token"]').getAttribute('content');
        
        fetch(endpoint, {
            method: 'POST',
            headers: {
                'X-CSRFToken': csrfToken
            },
            body: formData
        })
        .then(response => response.json())
        .then(data => resolve(data))
        .catch(error => reject(error));
    });
}

// Обработка ошибок API
async function handleApiError(response) {
    if (!response.ok) {
        let errorMessage = 'Ошибка сервера';
        
        try {
            const errorData = await response.json();
            errorMessage = errorData.error || errorData.message || errorMessage;
        } catch (e) {
            // Если ответ не JSON
            errorMessage = response.statusText || errorMessage;
        }
        
        showToast(errorMessage, 'error');
        throw new Error(errorMessage);
    }
    
    return response.json();
}

// Проверка онлайн статуса
function checkOnlineStatus() {
    if (!navigator.onLine) {
        showToast('Нет соединения с интернетом', 'error');
    }
}

// Периодическая проверка статуса
setInterval(checkOnlineStatus, 30000);

// Обработчик изменения онлайн статуса
window.addEventListener('online', () => {
    showToast('Соединение восстановлено', 'success');
});

window.addEventListener('offline', () => {
    showToast('Нет соединения с интернетом', 'error');
});

// Экспорт функций для использования в других файлах
window.App = {
    showToast,
    formatDate,
    escapeHtml,
    uploadFile,
    handleApiError
};