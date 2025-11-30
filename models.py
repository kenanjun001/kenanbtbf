from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from config import encrypt, decrypt

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    login_attempts = db.Column(db.Integer, default=0)
    locked_until = db.Column(db.DateTime, nullable=True)

class DatabaseConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    db_type = db.Column(db.String(20), nullable=False)  # mysql, postgresql, sqlite
    host = db.Column(db.String(255), default='localhost')
    port = db.Column(db.Integer)
    database = db.Column(db.String(255), nullable=False)
    username = db.Column(db.String(100))
    _password = db.Column('password', db.String(500))
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Schedule settings
    schedule_enabled = db.Column(db.Boolean, default=False)
    schedule_type = db.Column(db.String(20), default='daily')  # hourly, daily, weekly, custom
    schedule_time = db.Column(db.String(10), default='03:00')
    schedule_day = db.Column(db.Integer, default=0)  # 0=Monday for weekly
    schedule_cron = db.Column(db.String(100))  # custom cron expression
    
    backups = db.relationship('BackupHistory', backref='database', lazy=True, cascade='all, delete-orphan')
    
    @property
    def password(self):
        return decrypt(self._password) if self._password else ''
    
    @password.setter
    def password(self, value):
        self._password = encrypt(value) if value else ''
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'db_type': self.db_type,
            'host': self.host,
            'port': self.port,
            'database': self.database,
            'username': self.username,
            'enabled': self.enabled,
            'schedule_enabled': self.schedule_enabled,
            'schedule_type': self.schedule_type,
            'schedule_time': self.schedule_time,
            'schedule_day': self.schedule_day,
            'schedule_cron': self.schedule_cron,
            'last_backup': self.backups[-1].to_dict() if self.backups else None
        }

class BackupHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    database_id = db.Column(db.Integer, db.ForeignKey('database_config.id'), nullable=True)  # 允许为空（宝塔备份）
    filename = db.Column(db.String(255), nullable=False)
    file_size = db.Column(db.Integer)
    file_hash = db.Column(db.String(64))
    status = db.Column(db.String(20), default='pending')  # pending, success, failed
    error_message = db.Column(db.Text)
    duration = db.Column(db.Float)  # seconds
    tg_uploaded = db.Column(db.Boolean, default=False)
    tg_file_id = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'database_id': self.database_id,
            'database_name': self.database.name if self.database else None,
            'filename': self.filename,
            'file_size': self.file_size,
            'file_size_str': self.format_size(self.file_size),
            'file_hash': self.file_hash,
            'status': self.status,
            'error_message': self.error_message,
            'duration': round(self.duration, 2) if self.duration else None,
            'tg_uploaded': self.tg_uploaded,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }
    
    @staticmethod
    def format_size(size):
        if not size:
            return '0 B'
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size < 1024:
                return f'{size:.1f} {unit}'
            size /= 1024
        return f'{size:.1f} TB'

class SystemLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    level = db.Column(db.String(10), default='info')  # info, warning, error
    message = db.Column(db.Text, nullable=False)
    details = db.Column(db.Text)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'level': self.level,
            'message': self.message,
            'details': self.details,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }

class Settings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)
    value = db.Column(db.Text)
    
    @classmethod
    def get(cls, key, default=None):
        setting = cls.query.filter_by(key=key).first()
        return setting.value if setting else default
    
    @classmethod
    def set(cls, key, value):
        setting = cls.query.filter_by(key=key).first()
        if setting:
            setting.value = str(value)
        else:
            setting = cls(key=key, value=str(value))
            db.session.add(setting)
        db.session.commit()


class BtPanelConfig(db.Model):
    """宝塔面板配置"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    url = db.Column(db.String(255), nullable=False)  # 面板地址
    _api_key = db.Column('api_key', db.String(500), nullable=False)  # API密钥
    enabled = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # 关联的数据库配置
    databases = db.relationship('BtDatabaseConfig', backref='panel', lazy=True, cascade='all, delete-orphan')
    
    @property
    def api_key(self):
        return decrypt(self._api_key) if self._api_key else ''
    
    @api_key.setter
    def api_key(self, value):
        self._api_key = encrypt(value) if value else ''
    
    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'url': self.url,
            'enabled': self.enabled,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S')
        }


class BtDatabaseConfig(db.Model):
    """宝塔面板数据库定时备份配置"""
    id = db.Column(db.Integer, primary_key=True)
    panel_id = db.Column(db.Integer, db.ForeignKey('bt_panel_config.id'), nullable=False)
    bt_db_id = db.Column(db.Integer, nullable=False)  # 宝塔数据库ID
    db_name = db.Column(db.String(100), nullable=False)  # 数据库名称
    enabled = db.Column(db.Boolean, default=True)
    
    # 定时设置
    schedule_enabled = db.Column(db.Boolean, default=False)
    schedule_type = db.Column(db.String(20), default='minutes')  # minutes, hourly, daily, weekly
    schedule_time = db.Column(db.String(10), default='03:00')
    schedule_day = db.Column(db.Integer, default=0)  # 0=Monday for weekly
    schedule_minutes = db.Column(db.Integer, default=30)  # 每N分钟
    
    # 是否推送文件到TG
    push_to_tg = db.Column(db.Boolean, default=True)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    def to_dict(self):
        return {
            'id': self.id,
            'panel_id': self.panel_id,
            'panel_name': self.panel.name if self.panel else None,
            'bt_db_id': self.bt_db_id,
            'db_name': self.db_name,
            'enabled': self.enabled,
            'schedule_enabled': self.schedule_enabled,
            'schedule_type': self.schedule_type,
            'schedule_time': self.schedule_time,
            'schedule_day': self.schedule_day,
            'schedule_minutes': self.schedule_minutes,
            'push_to_tg': self.push_to_tg
        }
