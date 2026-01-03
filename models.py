from operator import or_, and_
from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy.orm import validates
from flask_migrate import Migrate
db = SQLAlchemy()


# Ассоциативные таблицы
post_likes = db.Table('post_likes',
    db.Column('user_id', db.Integer, db.ForeignKey('user.id'), primary_key=True),
    db.Column('post_id', db.Integer, db.ForeignKey('post.id'), primary_key=True)
)

# Модель для управления дружбой
class Friendship(db.Model):
    __tablename__ = 'friendships'
    
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    friend_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    status = db.Column(db.String(20), default='pending')  # pending, accepted, blocked
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    action_user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    
    # Связи
    user = db.relationship('User', foreign_keys=[user_id], backref='initiated_friendships')
    friend = db.relationship('User', foreign_keys=[friend_id], backref='received_friendships')
    action_user = db.relationship('User', foreign_keys=[action_user_id])
    
    # Уникальный индекс для пары user_id + friend_id
    __table_args__ = (
        db.UniqueConstraint('user_id', 'friend_id', name='unique_friendship'),
    )
    
    def __repr__(self):
        return f'<Friendship {self.user_id}-{self.friend_id}: {self.status}>'


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=True)
    password_hash = db.Column(db.String(200), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    is_online = db.Column(db.Boolean, default=False)
    
    # 2FA
    otp_secret = db.Column(db.String(32))
    is_2fa_enabled = db.Column(db.Boolean, default=False)
    
    # Отношения
    posts = db.relationship('Post', backref='author', lazy='dynamic', cascade='all, delete-orphan')
    sent_messages = db.relationship('Message', foreign_keys='Message.sender_id', 
                                   backref='sender', lazy='dynamic')
    received_messages = db.relationship('Message', foreign_keys='Message.receiver_id', 
                                       backref='receiver', lazy='dynamic')
    comments = db.relationship('Comment', backref='author', lazy='dynamic')
    
    @property
    def friends(self):
        """Получить список друзей (для обратной совместимости)"""
        # Друзья где пользователь является user_id
        friends_as_user = User.query.join(
            Friendship, Friendship.friend_id == User.id
        ).filter(
            Friendship.user_id == self.id,
            Friendship.status == 'accepted'
        ).all()
        
        # Друзья где пользователь является friend_id
        friends_as_friend = User.query.join(
            Friendship, Friendship.user_id == User.id
        ).filter(
            Friendship.friend_id == self.id,
            Friendship.status == 'accepted'
        ).all()
        
        # Объединяем и убираем дубликаты
        all_friends = list(set(friends_as_user + friends_as_friend))
        return all_friends
    
    def get_friends(self):
        """Получить список друзей"""
        return self.friends
    
    def is_friend(self, other_user):
        """Проверить, является ли пользователь другом"""
        friendship = Friendship.query.filter(
        (
            (Friendship.user_id == self.id) & 
            (Friendship.friend_id == other_user.id) & 
            (Friendship.status == 'accepted')
        ) | (
            (Friendship.user_id == other_user.id) & 
            (Friendship.friend_id == self.id) & 
            (Friendship.status == 'accepted')
            )
        ).first()
        return friendship is not None
    
    

class Post(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Отношения
    comments = db.relationship('Comment', backref='post', lazy='dynamic', 
                              cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Post {self.id} by {self.user_id}>'

class Comment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    post_id = db.Column(db.Integer, db.ForeignKey('post.id'), nullable=False)
    
    def __repr__(self):
        return f'<Comment {self.id} on post {self.post_id}>'

class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read = db.Column(db.Boolean, default=False)
    read_at = db.Column(db.DateTime, nullable=True)
    
    # Отправитель и получатель
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    # Шифрование
    is_encrypted = db.Column(db.Boolean, default=False)
    encryption_key = db.Column(db.String(500), nullable=True)  # Для E2E шифрования
    
    def __repr__(self):
        return f'<Message {self.id} from {self.sender_id} to {self.receiver_id}>'
    
    def mark_as_read(self):
        if not self.is_read:
            self.is_read = True
            self.read_at = datetime.utcnow()

class Notification(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # nullable=True если не всегда есть отправитель
    type = db.Column(db.String(50), nullable=False)  # 'friend_request', 'message', 'like', 'comment'
    content = db.Column(db.String(500))
    is_read = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    related_id = db.Column(db.Integer)  # ID связанного объекта
    
    # Связи (исправьте если нужно)
    user = db.relationship('User', foreign_keys=[user_id], backref='notifications')
    sender = db.relationship('User', foreign_keys=[sender_id])
    
    def __repr__(self):
        return f'<Notification {self.id} for user {self.user_id}>'