import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'your-production-secret-key-here'
    SESSION_PERMANENT = True
    PERMANENT_SESSION_LIFETIME = 604800  # 7 days
    # Removed email configuration - not used in current implementation