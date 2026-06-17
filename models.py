from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import secrets

db = SQLAlchemy()


class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.LargeBinary, nullable=False)
    role = db.Column(db.String(20), default='user')  # 'user' or 'admin'
    verified = db.Column(db.Boolean, default=False)
    verify_code = db.Column(db.String(10))
    token = db.Column(db.String(64), index=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    posts = db.relationship('Post', backref='user', cascade='all, delete-orphan')
    keys = db.relationship('ApiKey', backref='user', cascade='all, delete-orphan', uselist=False)

    def new_token(self):
        self.token = secrets.token_hex(32)
        return self.token

    def to_dict(self):
        return {
            'id': self.id,
            'email': self.email,
            'role': self.role,
            'verified': self.verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'post_count': len(self.posts),
            'has_api_key': bool(self.keys and (self.keys.text_key_enc or self.keys.image_key_enc)),
        }


class ApiKey(db.Model):
    __tablename__ = 'api_keys'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), unique=True, nullable=False)
    text_provider = db.Column(db.String(50))   # openai | deepseek | qwen
    text_key_enc = db.Column(db.LargeBinary)
    image_provider = db.Column(db.String(50))  # dalle | stability | wanxiang
    image_key_enc = db.Column(db.LargeBinary)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class SystemKey(db.Model):
    """Admin-managed fallback keys."""
    __tablename__ = 'system_keys'
    id = db.Column(db.Integer, primary_key=True)
    text_provider = db.Column(db.String(50))
    text_key_enc = db.Column(db.LargeBinary)
    image_provider = db.Column(db.String(50))
    image_key_enc = db.Column(db.LargeBinary)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Post(db.Model):
    __tablename__ = 'posts'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    topic = db.Column(db.Text)
    title = db.Column(db.Text)
    body = db.Column(db.Text)
    hashtags = db.Column(db.Text)
    image_prompt = db.Column(db.Text)
    images = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        import json
        return {
            'id': self.id,
            'user_id': self.user_id,
            'topic': self.topic,
            'title': self.title,
            'body': self.body,
            'hashtags': json.loads(self.hashtags) if self.hashtags else [],
            'image_prompt': self.image_prompt,
            'images': json.loads(self.images) if self.images else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }
