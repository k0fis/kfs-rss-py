import os

PORT = int(os.environ.get('PORT', 8180))
DB_NAME = os.environ.get('DB_NAME', 'kfs_rss')
DB_USER = os.environ.get('DB_USER', 'kofis')
DB_PASSWORD = os.environ.get('DB_PASSWORD', '')
DB_HOST = os.environ.get('DB_HOST', '')  # empty = Unix socket (local trust)
DB_PORT = int(os.environ.get('DB_PORT', 5432))

JWT_SECRET = os.environ.get('JWT_SECRET', 'dev-secret-change-me')

FETCH_TIMEOUT = int(os.environ.get('FETCH_TIMEOUT', 15))
RETENTION_DAYS = int(os.environ.get('RETENTION_DAYS', 30))
MAX_ARTICLES_PER_FEED = int(os.environ.get('MAX_ARTICLES_PER_FEED', 100))
USER_AGENT = os.environ.get('USER_AGENT', 'kfs-rss/3.0')
