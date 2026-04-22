import base64
import hashlib
import hmac
import json
import time
from functools import wraps
from flask import request, g, jsonify
import rss_config as cfg
import rss_db as db


def _validate_token(token):
    parts = token.split('.')
    if len(parts) != 3:
        return None
    header_payload = parts[0] + '.' + parts[1]
    expected = base64.urlsafe_b64encode(
        hmac.new(cfg.JWT_SECRET.encode(), header_payload.encode(), hashlib.sha256).digest()
    ).rstrip(b'=').decode()
    if not hmac.compare_digest(parts[2], expected):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + '=='))
    except Exception:
        return None
    if payload.get('exp', 0) < time.time():
        return None
    return payload.get('sub')


def _ensure_user(username):
    row = db.query_one('SELECT id FROM users WHERE username = %s', (username,))
    if row:
        return row['id']
    result = db.execute_returning(
        'INSERT INTO users (username, created_at) VALUES (%s, NOW()) '
        'ON CONFLICT (username) DO UPDATE SET username = EXCLUDED.username '
        'RETURNING id',
        (username,)
    )
    return result['id']


def require_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify(error='Missing or invalid token'), 401
        username = _validate_token(auth[7:])
        if not username:
            return jsonify(error='Invalid or expired token'), 401
        g.username = username
        g.user_id = _ensure_user(username)
        return f(*args, **kwargs)
    return decorated
