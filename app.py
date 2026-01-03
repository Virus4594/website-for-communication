from operator import or_, and_
import os
import json
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_talisman import Talisman
from flask_wtf import CSRFProtect
from models import db, User, Post, Comment, Message, Notification, Friendship, post_likes
from flask_migrate import Migrate
import qrcode
from io import BytesIO
import base64

from config import Config
from auth import (
    login_required, validate_password, validate_username, 
    hash_password, verify_password, generate_otp_secret,
    verify_otp_token, get_otp_uri
)

# Инициализация приложения
app = Flask(__name__)
app.config.from_object(Config)
# Расширения
csrf = CSRFProtect(app)
db.init_app(app)
migrate = Migrate(app, db)
socketio = SocketIO(app, cors_allowed_origins="*", logger=True, engineio_logger=True)
limiter = Limiter(app=app, key_func=get_remote_address)

# Заголовки безопасности
Talisman(app, 
    content_security_policy={
        'default-src': ["'self'"],
        'script-src': ["'self'", "'unsafe-inline'", "https://cdn.socket.io"],
        'style-src': ["'self'", "'unsafe-inline'", "https://fonts.googleapis.com"],
        'font-src': ["'self'", "https://fonts.gstatic.com"],
        'connect-src': ["'self'", "ws:", "wss:"],
        'img-src': ["'self'", "data:", "https:"]
    }
)

# Хранилище для статуса "печатает"
typing_users = {}

# ========================
# Роуты аутентификации
# ========================

@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('feed'))
    return render_template('index.html')

@app.route('/register', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def register():
    if request.method == 'GET':
        return render_template('auth/register.html')
    
    # Обработка регистрации
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    confirm_password = request.form.get('confirm_password', '')
    
    # Валидация
    if not username or not password:
        flash('Заполните все поля', 'error')
        return redirect(url_for('register'))
    
    if password != confirm_password:
        flash('Пароли не совпадают', 'error')
        return redirect(url_for('register'))
    
    username_error = validate_username(username)
    if username_error:
        flash(username_error, 'error')
        return redirect(url_for('register'))
    
    password_error = validate_password(password)
    if password_error:
        flash(password_error, 'error')
        return redirect(url_for('register'))
    
    # Проверка существующего пользователя
    existing_user = User.query.filter_by(username=username).first()
    if existing_user:
        flash('Имя пользователя уже занято', 'error')
        return redirect(url_for('register'))
    
    try:
        # Создание пользователя
        hashed_password = hash_password(password)
        new_user = User(
            username=username,
            password_hash=hashed_password,
            created_at=datetime.utcnow()
        )
        
        db.session.add(new_user)
        db.session.commit()
        
        session['user_id'] = new_user.id
        flash('Регистрация успешна!', 'success')
        return redirect(url_for('profile'))
        
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка регистрации: {str(e)}', 'error')
        return redirect(url_for('register'))

@app.route('/login', methods=['GET', 'POST'])
@limiter.limit("10 per minute")
def login():
    if request.method == 'GET':
        return render_template('auth/login.html')
    
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    
    if not username or not password:
        flash('Заполните все поля', 'error')
        return redirect(url_for('login'))
    
    user = User.query.filter_by(username=username).first()
    
    if not user or not verify_password(user.password_hash, password):
        flash('Неверное имя пользователя или пароль', 'error')
        return redirect(url_for('login'))
    
    # Если включена 2FA
    if user.is_2fa_enabled:
        session['pre_2fa_user_id'] = user.id
        return redirect(url_for('verify_2fa_login'))
    
    # Стандартный вход
    session['user_id'] = user.id
    user.last_seen = datetime.utcnow()
    user.is_online = True
    db.session.commit()
    
    flash('Вход выполнен успешно!', 'success')
    return redirect(url_for('feed'))

@app.route('/verify_2fa_login', methods=['GET', 'POST'])
def verify_2fa_login():
    if 'pre_2fa_user_id' not in session:
        return redirect(url_for('login'))
    
    user = User.query.get(session['pre_2fa_user_id'])
    
    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        
        if not token or not verify_otp_token(user.otp_secret, token):
            flash('Неверный код аутентификации', 'error')
            return render_template('auth/verify_2fa.html')
        
        session['user_id'] = user.id
        session.pop('pre_2fa_user_id', None)
        user.last_seen = datetime.utcnow()
        user.is_online = True
        db.session.commit()
        
        flash('Вход выполнен успешно!', 'success')
        return redirect(url_for('feed'))
    
    return render_template('auth/verify_2fa.html')

@app.route('/logout')
@login_required
def logout():
    user_id = session.get('user_id')
    if user_id:
        user = User.query.get(user_id)
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
    
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('index'))

# ========================
# 2FA Роуты
# ========================

@app.route('/enable_2fa')
@login_required
def enable_2fa():
    user = User.query.get(session['user_id'])
    
    if not user.otp_secret:
        user.otp_secret = generate_otp_secret()
        db.session.commit()
    
    # Генерация QR-кода
    otp_uri = get_otp_uri(user.username, user.otp_secret)
    qr = qrcode.make(otp_uri)
    
    buffered = BytesIO()
    qr.save(buffered, format="PNG")
    qr_base64 = base64.b64encode(buffered.getvalue()).decode()
    
    return render_template('profile/settings.html', 
                         qr_code=qr_base64,
                         otp_secret=user.otp_secret)

@app.route('/disable_2fa', methods=['POST'])
@login_required
def disable_2fa():
    user = User.query.get(session['user_id'])
    user.otp_secret = None
    user.is_2fa_enabled = False
    db.session.commit()
    
    flash('Двухфакторная аутентификация отключена', 'success')
    return redirect(url_for('profile'))

@app.route('/verify_2fa', methods=['POST'])
@login_required
def verify_2fa():
    user = User.query.get(session['user_id'])
    token = request.form.get('token', '').strip()
    
    if not token or not verify_otp_token(user.otp_secret, token):
        flash('Неверный код аутентификации', 'error')
        return redirect(url_for('enable_2fa'))
    
    user.is_2fa_enabled = True
    db.session.commit()
    
    flash('Двухфакторная аутентификация включена', 'success')
    return redirect(url_for('profile'))

# ========================
# Профиль и настройки
# ========================

@app.route('/profile')
@login_required
def profile():
    user = User.query.get(session['user_id'])
    recent_posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).limit(5).all()
    return render_template('profile/profile.html', 
                         user=user, 
                         recent_posts=recent_posts,
                         current_user=user)

@app.route('/profile/<username>')
@login_required
def user_profile(username):
    current_user_id = session['user_id']
    current_user = User.query.get(current_user_id)
    user = User.query.filter_by(username=username).first_or_404()
    
    # ИСПРАВЛЕННАЯ проверка дружбы (используем Friendship модель):
    are_friends = Friendship.query.filter(
        (
            (Friendship.user_id == current_user_id) & 
            (Friendship.friend_id == user.id) & 
            (Friendship.status == 'accepted')
        ) | (
            (Friendship.user_id == user.id) & 
            (Friendship.friend_id == current_user_id) & 
            (Friendship.status == 'accepted')
        )
    ).first() is not None
    
    # Получаем последние посты пользователя
    recent_posts = Post.query.filter_by(user_id=user.id).order_by(Post.created_at.desc()).limit(5).all()
    
    return render_template('profile/profile.html', 
                         user=user, 
                         is_friend=are_friends,
                         recent_posts=recent_posts,
                         current_user=current_user)

@app.route('/settings', methods=['GET', 'POST'])
@login_required
def settings():
    user = User.query.get(session['user_id'])
    
    if request.method == 'POST':
        # Обновление настроек
        new_username = request.form.get('username', '').strip()
        
        if new_username and new_username != user.username:
            existing = User.query.filter_by(username=new_username).first()
            if existing:
                flash('Имя пользователя уже занято', 'error')
            else:
                user.username = new_username
                db.session.commit()
                flash('Имя пользователя обновлено', 'success')
        
        # Смена пароля
        current_password = request.form.get('current_password', '')
        new_password = request.form.get('new_password', '')
        
        if current_password and new_password:
            if verify_password(user.password_hash, current_password):
                password_error = validate_password(new_password)
                if password_error:
                    flash(password_error, 'error')
                else:
                    user.password_hash = hash_password(new_password)
                    db.session.commit()
                    flash('Пароль изменен', 'success')
            else:
                flash('Текущий пароль неверен', 'error')
    
    return render_template('profile/settings.html', user=user)

# ========================
# Лента и посты
# ========================

@app.route('/feed')
@login_required
def feed():
    # Получаем ID текущего пользователя
    user_id = session['user_id']
    user = User.query.get(user_id)
    
    # Получаем ID друзей
    friend_ids = [user_id]
    
    # Запросы где пользователь является user_id
    friendships_as_user = Friendship.query.filter(
        Friendship.user_id == user_id,
        Friendship.status == 'accepted'
    ).all()
    
    # Запросы где пользователь является friend_id
    friendships_as_friend = Friendship.query.filter(
        Friendship.friend_id == user_id,
        Friendship.status == 'accepted'
    ).all()
    
    # Собираем ID друзей
    for fs in friendships_as_user:
        friend_ids.append(fs.friend_id)
    
    for fs in friendships_as_friend:
        friend_ids.append(fs.user_id)
    
    # Убираем дубликаты
    friend_ids = list(set(friend_ids))
    
    # Получаем посты
    posts = Post.query.filter(Post.user_id.in_(friend_ids)) \
                      .order_by(Post.created_at.desc()) \
                      .limit(50) \
                      .all()
    
    return render_template('index.html', posts=posts)

@app.route('/create_post', methods=['GET', 'POST'])
@login_required
def create_post():
    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        content = request.form.get('content', '').strip()
        
        if not title or not content:
            flash('Заполните все поля', 'error')
            return redirect(url_for('create_post'))
        
        if len(title) > 120:
            flash('Заголовок слишком длинный', 'error')
            return redirect(url_for('create_post'))
        
        new_post = Post(
            title=title,
            content=content,
            user_id=session['user_id'],
            created_at=datetime.utcnow()
        )
        
        db.session.add(new_post)
        db.session.commit()
        
        flash('Пост опубликован', 'success')
        return redirect(url_for('feed'))
    
    return render_template('posts/create_post.html')

@app.route('/post/<int:post_id>')
@login_required
def post_detail(post_id):
    post = Post.query.get_or_404(post_id)
    return render_template('posts/post_detail.html', post=post)

@app.route('/like_post/<int:post_id>', methods=['POST'])
@login_required
def like_post(post_id):
    post = Post.query.get_or_404(post_id)
    user = User.query.get(session['user_id'])
    
    if user in post.likes:
        post.likes.remove(user)
        liked = False
    else:
        post.likes.append(user)
        liked = True
        
        # Создаем уведомление
        if post.author.id != user.id:
            notification = Notification(
                user_id=post.author.id,
                type='like',
                content=f'{user.username} понравился ваш пост',
                related_id=post.id
            )
            db.session.add(notification)
    
    db.session.commit()
    
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return jsonify({
            'liked': liked,
            'likes_count': len(post.likes)
        })
    
    return redirect(request.referrer or url_for('feed'))

@app.route('/comment/<int:post_id>', methods=['POST'])
@login_required
def add_comment(post_id):
    post = Post.query.get_or_404(post_id)
    content = request.form.get('content', '').strip()
    
    if not content:
        flash('Комментарий не может быть пустым', 'error')
        return redirect(url_for('post_detail', post_id=post_id))
    
    comment = Comment(
        content=content,
        user_id=session['user_id'],
        post_id=post_id,
        created_at=datetime.utcnow()
    )
    
    db.session.add(comment)
    
    # Уведомление автору поста
    if post.author.id != session['user_id']:
        user = User.query.get(session['user_id'])
        notification = Notification(
            user_id=post.author.id,
            type='comment',
            content=f'{user.username} прокомментировал ваш пост',
            related_id=post.id
        )
        db.session.add(notification)
    
    db.session.commit()
    
    return redirect(url_for('post_detail', post_id=post_id))

# ========================
# Друзья
# ========================

@app.route('/search')
@login_required
def search():
    """Поиск пользователей"""
    try:
        query = request.args.get('q', '').strip()
        current_user_id = session['user_id']
        current_user = User.query.get(current_user_id)
        
        users = []
        if query:
            # Простой поиск по имени
            users = User.query.filter(
                User.username.ilike(f'%{query}%'),
                User.id != current_user_id
            ).limit(30).all()
        
        # Простой список пользователей без сложной логики статусов
        return render_template('friend/search.html', 
                             users=users, 
                             query=query,
                             current_user=current_user)
    except Exception as e:
        print(f"Ошибка в поиске: {e}")
        import traceback
        traceback.print_exc()
        
        # Возвращаем простую страницу с ошибкой
        return f"""
        <html>
        <head><title>Ошибка поиска</title></head>
        <body>
            <h1>Ошибка в поиске</h1>
            <p>Произошла ошибка: {str(e)}</p>
            <a href="/">Вернуться на главную</a>
        </body>
        </html>
        """, 500

@app.route('/friends')
@login_required
def friends():
    """Страница друзей"""
    current_user = User.query.get(session['user_id'])
    if not current_user:
        return redirect(url_for('auth.login'))
    
    current_user_id = current_user.id
    
    # ВАРИАНТ 1: Используя модель Friendship
    # Входящие запросы
    incoming_friendships = Friendship.query.filter(
        Friendship.friend_id == current_user_id,
        Friendship.status == 'pending'
    ).all()
    
    incoming_requests = []
    for friendship in incoming_friendships:
        user = User.query.get(friendship.user_id)
        if user:
            incoming_requests.append(user)
    
    # Исходящие запросы
    outgoing_friendships = Friendship.query.filter(
        Friendship.user_id == current_user_id,
        Friendship.status == 'pending'
    ).all()
    
    outgoing_requests = []
    for friendship in outgoing_friendships:
        user = User.query.get(friendship.friend_id)
        if user:
            outgoing_requests.append(user)
    
    # Друзья (принятые запросы)
    friendships_as_user = Friendship.query.filter(
        Friendship.user_id == current_user_id,
        Friendship.status == 'accepted'
    ).all()
    
    friendships_as_friend = Friendship.query.filter(
        Friendship.friend_id == current_user_id,
        Friendship.status == 'accepted'
    ).all()
    
    friends_list = []
    friend_ids = set()
    
    for friendship in friendships_as_user:
        friend = User.query.get(friendship.friend_id)
        if friend and friend.id not in friend_ids:
            friends_list.append(friend)
            friend_ids.add(friend.id)
    
    for friendship in friendships_as_friend:
        friend = User.query.get(friendship.user_id)
        if friend and friend.id not in friend_ids:
            friends_list.append(friend)
            friend_ids.add(friend.id)
    
    return render_template('friend/friends.html',
                         incoming_requests=incoming_requests,
                         outgoing_requests=outgoing_requests,
                         friends=friends_list,
                         current_user=current_user)

@app.route('/accept_friend/<int:friend_id>', methods=['POST'])
@login_required
def accept_friend(friend_id):
    """Тестовый маршрут без CSRF"""
    try:
        current_user_id = session['user_id']
        current_user = User.query.get(current_user_id)
        friend = User.query.get_or_404(friend_id)
        
        print(f"TEST: Принимаем запрос от {friend_id}")
        
        # Находим запрос
        friendship = Friendship.query.filter(
            (Friendship.user_id == friend_id) &
            (Friendship.friend_id == current_user_id) &
            (Friendship.status == 'pending')
        ).first()
        
        if friendship:
            friendship.status = 'accepted'
            db.session.commit()
            flash('Запрос принят (тест)', 'success')
        else:
            flash('Запрос не найден', 'error')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        
    return redirect(url_for('friends'))


@app.route('/reject_friend/<int:friend_id>', methods=['POST'])
@login_required 
def reject_friend(friend_id):
    """Тестовый маршрут без CSRF"""
    try:
        current_user_id = session['user_id']
        
        # Удаляем запрос
        friendship = Friendship.query.filter(
            (Friendship.user_id == friend_id) &
            (Friendship.friend_id == current_user_id) &
            (Friendship.status == 'pending')
        ).first()
        
        if friendship:
            db.session.delete(friendship)
            db.session.commit()
            flash('Запрос отклонен (тест)', 'info')
        else:
            flash('Запрос не найден', 'error')
            
    except Exception as e:
        db.session.rollback()
        flash(f'Ошибка: {str(e)}', 'error')
        
    return redirect(url_for('friends'))


@app.route('/add_friend/<int:user_id>', methods=['POST'])
@login_required
def add_friend(user_id):
    # user_id - это ID пользователя, которого хотим добавить в друзья
    user_to_add = User.query.get_or_404(user_id)
    
    # ID текущего пользователя
    current_user_id = session['user_id']
    current_user = User.query.get(current_user_id)
    
    # Проверка на добавление самого себя
    if current_user_id == user_id:
        flash('Нельзя отправить запрос самому себе', 'error')
        return redirect(url_for('profile', username=user_to_add.username))
    
    # Проверяем существующие отношения
    existing_friendship = Friendship.query.filter(
    or_(
        and_(Friendship.user_id == current_user_id, 
             Friendship.friend_id == user_id),
        and_(Friendship.user_id == user_id, 
             Friendship.friend_id == current_user_id)
        )
    ).first()
    
    if existing_friendship:
        if existing_friendship.status == 'pending':
            flash('Запрос уже отправлен', 'warning')
        elif existing_friendship.status == 'accepted':
            flash('Вы уже друзья', 'info')
        return redirect(url_for('profile', username=user_to_add.username))
    
    # Создаем запрос на дружбу
    new_friendship = Friendship(
        user_id=current_user_id,
        friend_id=user_id,
        status='pending',
        action_user_id=current_user_id,
        created_at=datetime.utcnow()
    )
    
    db.session.add(new_friendship)
    db.session.commit()  # Сначала коммитим, чтобы получить ID
    
    # Теперь СОЗДАЕМ УВЕДОМЛЕНИЕ для получателя
    notification = Notification(
        user_id=user_id,  # Кто получит уведомление
        sender_id=current_user_id,  # Кто отправил
        type='friend_request',
        content=f'Пользователь {current_user.username} отправил вам запрос на дружбу',
        is_read=False,
        created_at=datetime.utcnow(),
        related_id=new_friendship.id  # Теперь ID доступен
    )
    
    db.session.add(notification)
    db.session.commit()  # Коммитим уведомление
    
    flash('Запрос в друзья отправлен', 'success')
    return redirect(url_for('profile', username=user_to_add.username))


@app.route('/remove_friend/<int:friend_id>', methods=['POST'])
@login_required
def remove_friend(friend_id):
    """Удалить из друзей"""
    try:
        current_user_id = session['user_id']
        
        # ИСПРАВЛЕННЫЙ запрос (используем Friendship модель):
        friendships = Friendship.query.filter(
    or_(
        and_(Friendship.user_id == current_user_id, 
             Friendship.friend_id == friend_id),
        and_(Friendship.user_id == friend_id, 
             Friendship.friend_id == current_user_id)
        )
    ).all()
        
        for friendship in friendships:
            db.session.delete(friendship)
        
        db.session.commit()
        
        friend = User.query.get(friend_id)
        flash(f'👋 {friend.username} удален из друзей', 'info')
        
    except Exception as e:
        db.session.rollback()
        print(f"Ошибка удаления друга: {e}")
        flash('Ошибка при удалении из друзей', 'error')
    
    return redirect(url_for('friends'))

@app.route('/notifications')
@login_required
def notifications():
    """Страница уведомлений"""
    try:
        user_id = session['user_id']
        user = User.query.get(user_id)
        
        if not user:
            flash('Пользователь не найден', 'error')
            return redirect(url_for('login'))
        
        # Получаем все уведомления пользователя
        notifications_list = Notification.query.filter_by(
            user_id=user_id
        ).order_by(Notification.created_at.desc()).all()
        
        # Получаем информацию об отправителях для уведомлений
        notifications_with_senders = []
        for notification in notifications_list:
            sender = None
            if notification.sender_id:
                sender = User.query.get(notification.sender_id)
            
            notifications_with_senders.append({
                'notification': notification,
                'sender': sender
            })
        
        # Помечаем как прочитанные при просмотре
        for notification in notifications_list:
            if not notification.is_read:
                notification.is_read = True
        
        db.session.commit()
        
        return render_template('notifications.html', 
                             notifications=notifications_with_senders,
                             current_user=user)
        
    except Exception as e:
        print(f"Ошибка в notifications: {str(e)}")
        import traceback
        traceback.print_exc()
        flash(f'Ошибка загрузки уведомлений: {str(e)}', 'error')
        return redirect(url_for('feed'))


@app.route('/notifications/count')
@login_required
def notifications_count():
    """API для получения количества непрочитанных уведомлений"""
    user_id = session['user_id']
    count = Notification.query.filter_by(
        user_id=user_id,
        is_read=False
    ).count()
    
    return jsonify({'count': count})

# ========================
# Сообщения и чат
# ========================

@app.route('/messages')
@login_required
def messages():
    user = User.query.get(session['user_id'])
    
    # Получаем последнее сообщение с каждым пользователем
    conversations = []
    
    # Все собеседники
    sent_conversations = db.session.query(
        Message.receiver_id,
        db.func.max(Message.created_at).label('last_message')
    ).filter(Message.sender_id == user.id).group_by(Message.receiver_id)
    
    received_conversations = db.session.query(
        Message.sender_id,
        db.func.max(Message.created_at).label('last_message')
    ).filter(Message.receiver_id == user.id).group_by(Message.sender_id)
    
    # Объединяем и сортируем
    all_conversations = {}
    
    for receiver_id, last_message in sent_conversations:
        all_conversations[receiver_id] = last_message
    
    for sender_id, last_message in received_conversations:
        if sender_id in all_conversations:
            if last_message > all_conversations[sender_id]:
                all_conversations[sender_id] = last_message
        else:
            all_conversations[sender_id] = last_message
    
    # Получаем информацию о собеседниках
    for other_user_id, last_message in sorted(all_conversations.items(), 
                                             key=lambda x: x[1], 
                                             reverse=True):
        other_user = User.query.get(other_user_id)
        if other_user:
            # Непрочитанные сообщения
            unread_count = Message.query.filter_by(
                sender_id=other_user_id,
                receiver_id=user.id,
                is_read=False
            ).count()
            
            conversations.append({
                'user': other_user,
                'last_message': last_message,
                'unread_count': unread_count
            })
    
    return render_template('messages/inbox.html', conversations=conversations)

@app.route('/chat/<username>')
@login_required
def chat(username):
    current_user = User.query.get(session['user_id'])
    other_user = User.query.filter_by(username=username).first_or_404()
    
    # ИСПРАВЛЕННАЯ проверка дружбы:
    are_friends = Friendship.query.filter(
        (
            (Friendship.user_id == current_user.id) & 
            (Friendship.friend_id == other_user.id) & 
            (Friendship.status == 'accepted')
        ) | (
            (Friendship.user_id == other_user.id) & 
            (Friendship.friend_id == current_user.id) & 
            (Friendship.status == 'accepted')
        )
    ).first() is not None
    
    if not are_friends:
        flash('Вы можете писать только друзьям', 'error')
        return redirect(url_for('messages'))
    
    # Получаем переписку
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user.id)) |
        ((Message.sender_id == other_user.id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.created_at.asc()).all()
    
    # Помечаем сообщения как прочитанные
    unread_messages = Message.query.filter_by(
        sender_id=other_user.id,
        receiver_id=current_user.id,
        is_read=False
    ).all()
    
    for msg in unread_messages:
        msg.mark_as_read()
    
    db.session.commit()
    
    return render_template('messages/chat.html',
                         other_user=other_user,
                         messages=messages)

# ========================
# WebSocket обработчики
# ========================

@socketio.on('connect')
def handle_connect():
    if 'user_id' in session:
        user_id = session['user_id']
        join_room(f'user_{user_id}')
        
        user = User.query.get(user_id)
        if user:
            user.is_online = True
            user.last_seen = datetime.utcnow()
            db.session.commit()
        
        print(f'Пользователь {user_id} подключился')
        emit('user_status', {'user_id': user_id, 'status': 'online'}, broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    if 'user_id' in session:
        user_id = session['user_id']
        user = User.query.get(user_id)
        if user:
            user.is_online = False
            user.last_seen = datetime.utcnow()
            db.session.commit()
        
        print(f'Пользователь {user_id} отключился')
        emit('user_status', {'user_id': user_id, 'status': 'offline'}, broadcast=True)

@socketio.on('join_chat')
def handle_join_chat(data):
    other_user_id = data.get('other_user_id')
    if other_user_id and 'user_id' in session:
        user_id = session['user_id']
        room_name = f'chat_{min(user_id, other_user_id)}_{max(user_id, other_user_id)}'
        join_room(room_name)
        print(f'Пользователь {user_id} присоединился к чату с {other_user_id}')

@socketio.on('send_message')
def handle_send_message(data):
    try:
        text = data.get('text', '').strip()
        receiver_id = data.get('receiver_id')
        
        if not text or not receiver_id:
            emit('error', {'message': 'Неверные данные'})
            return
        
        sender_id = session.get('user_id')
        if not sender_id:
            emit('error', {'message': 'Требуется авторизация'})
            return
        
        # ИСПРАВЛЕННАЯ проверка дружбы:
        sender = User.query.get(sender_id)
        receiver = User.query.get(receiver_id)
        
        # Проверяем через Friendship модель
        are_friends = Friendship.query.filter(
            (
                (Friendship.user_id == sender_id) & 
                (Friendship.friend_id == receiver_id) & 
                (Friendship.status == 'accepted')
            ) | (
                (Friendship.user_id == receiver_id) & 
                (Friendship.friend_id == sender_id) & 
                (Friendship.status == 'accepted')
            )
        ).first() is not None
        
        if not are_friends:
            emit('error', {'message': 'Вы можете писать только друзьям'})
            return
        
        # Сохраняем сообщение
        message = Message(
            content=text,
            sender_id=sender_id,
            receiver_id=receiver_id,
            created_at=datetime.utcnow()
        )
        
        db.session.add(message)
        
        # Уведомление
        notification = Notification(
            user_id=receiver_id,
            type='message',
            content=f'Новое сообщение от {sender.username}',
            related_id=sender_id
        )
        db.session.add(notification)
        
        db.session.commit()
        
        # Формируем данные для отправки
        message_data = {
            'id': message.id,
            'text': message.content,
            'sender_id': sender_id,
            'sender_username': sender.username,
            'receiver_id': receiver_id,
            'created_at': message.created_at.isoformat(),
            'is_read': message.is_read
        }
        
        # Отправляем в комнату чата
        room_name = f'chat_{min(sender_id, receiver_id)}_{max(sender_id, receiver_id)}'
        emit('new_message', message_data, room=room_name)
        
        # Уведомляем получателя
        emit('message_notification', message_data, room=f'user_{receiver_id}')
        
        print(f'Сообщение от {sender_id} к {receiver_id} отправлено')
        
    except Exception as e:
        print(f'Ошибка отправки сообщения: {e}')
        emit('error', {'message': 'Ошибка сервера'})
        db.session.rollback()

@socketio.on('typing')
def handle_typing(data):
    receiver_id = data.get('receiver_id')
    if receiver_id and 'user_id' in session:
        sender_id = session['user_id']
        sender = User.query.get(sender_id)
        
        emit('user_typing', {
            'sender_id': sender_id,
            'sender_username': sender.username
        }, room=f'user_{receiver_id}')

@socketio.on('read_message')
def handle_read_message(data):
    message_id = data.get('message_id')
    if message_id:
        message = Message.query.get(message_id)
        if message and message.receiver_id == session.get('user_id'):
            message.mark_as_read()
            db.session.commit()

# ========================
# API для фронтенда
# ========================

@app.route('/api/messages/<int:user_id>')
@login_required
def api_get_messages(user_id):
    current_user_id = session['user_id']
    
    # Проверяем дружбу перед выдачей сообщений
    are_friends = Friendship.query.filter(
        (
            (Friendship.user_id == current_user_id) & 
            (Friendship.friend_id == user_id) & 
            (Friendship.status == 'accepted')
        ) | (
            (Friendship.user_id == user_id) & 
            (Friendship.friend_id == current_user_id) & 
            (Friendship.status == 'accepted')
        )
    ).first() is not None
    
    if not are_friends:
        return jsonify({'error': 'Вы не друзья с этим пользователем'}), 403
    
    messages = Message.query.filter(
        ((Message.sender_id == current_user_id) & (Message.receiver_id == user_id)) |
        ((Message.sender_id == user_id) & (Message.receiver_id == current_user_id))
    ).order_by(Message.created_at.asc()).all()
    
    messages_data = []
    for msg in messages:
        messages_data.append({
            'id': msg.id,
            'text': msg.content,
            'sender_id': msg.sender_id,
            'sender_username': msg.sender.username,
            'receiver_id': msg.receiver_id,
            'created_at': msg.created_at.isoformat(),
            'is_read': msg.is_read,
            'is_mine': msg.sender_id == current_user_id
        })
    
    return jsonify({'messages': messages_data})

@app.route('/api/notifications')
@login_required
def api_get_notifications():
    notifications = Notification.query.filter_by(
        user_id=session['user_id'],
        is_read=False
    ).order_by(Notification.created_at.desc()).limit(20).all()
    
    notifications_data = []
    for notif in notifications:
        notifications_data.append({
            'id': notif.id,
            'type': notif.type,
            'content': notif.content,
            'created_at': notif.created_at.isoformat(),
            'related_id': notif.related_id
        })
    
    return jsonify({'notifications': notifications_data})

@app.route('/api/notifications/read/<int:notification_id>', methods=['POST'])
@login_required
def api_mark_notification_read(notification_id):
    notification = Notification.query.get_or_404(notification_id)
    
    if notification.user_id != session['user_id']:
        return jsonify({'error': 'Доступ запрещен'}), 403
    
    notification.is_read = True
    db.session.commit()
    
    return jsonify({'success': True})

@app.route('/api/user/status/<int:user_id>')
@login_required
def api_get_user_status(user_id):
    user = User.query.get(user_id)
    if user:
        return jsonify({
            'is_online': user.is_online,
            'last_seen': user.last_seen.isoformat() if user.last_seen else None
        })
    return jsonify({'error': 'Пользователь не найден'}), 404

# ========================
# Утилиты и обработчики ошибок
# ========================

@app.context_processor
def inject_user():
    """Добавляет текущего пользователя во все шаблоны"""
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        return {'current_user': user}
    return {}

@app.errorhandler(404)
def not_found_error(error):
    return render_template('errors/404.html'), 404

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    return render_template('errors/500.html'), 500

@app.before_request
def update_last_seen():
    if 'user_id' in session:
        user = User.query.get(session['user_id'])
        if user:
            user.last_seen = datetime.utcnow()
            db.session.commit()

# ========================
# Точка входа
# ========================

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    
    print("Запуск сервера на http://localhost:5000")
    socketio.run(app, 
                 host='0.0.0.0',
                 port=5000,
                 debug=True,
                 allow_unsafe_werkzeug=True)