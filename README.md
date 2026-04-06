# Flask Social Network / Messenger
(Сделано для теста)
Веб-приложение на Flask с функционалом социальной сети и встроенного мессенджера в реальном времени.

## 🚀 Возможности

- Регистрация и авторизация пользователей
- Двухфакторная аутентификация (2FA, TOTP)
- Профили пользователей
- Система друзей (заявки, принятие, удаление)
- Лента постов
- Комментарии и лайки
- Уведомления
- Личные сообщения
- Чат в реальном времени (Flask-SocketIO)
- Статусы онлайн / офлайн
- Защита CSRF, rate limit, security headers

## 🛠️ Стек технологий

- Python 3.10+
- Flask
- Flask-SQLAlchemy
- Flask-Migrate
- Flask-SocketIO
- Flask-WTF
- Flask-Limiter
- Flask-Talisman
- pyotp
- qrcode
- SQLite (по умолчанию)
- HTML / Jinja2
## ⚙️ Установка и запуск

### 1. Клонирование репозитория
```bash
git clone https://github.com/Virus4594/website-for-communication.git
cd REPOSITORY_NAME
### 2. Создание вертуального окружения
python -m venv venv
source venv/bin/activate  # Linux / macOS
venv\Scripts\activate     # Windows
### 3. Установка зависимости
pip install -r requirements.txt
### 4. Запуск
python app.py


