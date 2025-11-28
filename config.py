import os
import base64
from pathlib import Path
from cryptography.fernet import Fernet
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).parent
BACKUP_DIR = Path(os.getenv('BACKUP_DIR', './backups')).resolve()
BACKUP_DIR.mkdir(parents=True, exist_ok=True)

# Encryption
def get_or_create_key():
    key = os.getenv('ENCRYPTION_KEY')
    if not key:
        key = Fernet.generate_key().decode()
        env_path = BASE_DIR / '.env'
        with open(env_path, 'a') as f:
            f.write(f'\nENCRYPTION_KEY={key}\n')
    return key.encode() if isinstance(key, str) else key

ENCRYPTION_KEY = get_or_create_key()
cipher = Fernet(ENCRYPTION_KEY)

def encrypt(text: str) -> str:
    if not text:
        return ''
    return cipher.encrypt(text.encode()).decode()

def decrypt(token: str) -> str:
    if not token:
        return ''
    try:
        return cipher.decrypt(token.encode()).decode()
    except:
        return token

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret-key-change-me')
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{BASE_DIR}/data.db'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    TG_BOT_TOKEN = os.getenv('TG_BOT_TOKEN', '')
    TG_CHAT_IDS = [x.strip() for x in os.getenv('TG_CHAT_IDS', '').split(',') if x.strip()]
    
    ADMIN_USERNAME = os.getenv('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD', 'admin123')
    
    MAX_LOCAL_BACKUPS = int(os.getenv('MAX_LOCAL_BACKUPS', 10))
    MAX_LOGIN_ATTEMPTS = 5
    LOGIN_LOCKOUT_MINUTES = 15
