import base64
import hashlib
import hmac
import json
import time
from rss_jwt import _validate_token
import rss_config as cfg


def _make_token(sub='testuser', exp=None, secret=None):
    if exp is None:
        exp = int(time.time()) + 3600
    if secret is None:
        secret = cfg.JWT_SECRET
    header = base64.urlsafe_b64encode(json.dumps({'alg': 'HS256', 'typ': 'JWT'}).encode()).rstrip(b'=').decode()
    payload = base64.urlsafe_b64encode(json.dumps({'sub': sub, 'exp': exp}).encode()).rstrip(b'=').decode()
    sig = base64.urlsafe_b64encode(
        hmac.new(secret.encode(), f'{header}.{payload}'.encode(), hashlib.sha256).digest()
    ).rstrip(b'=').decode()
    return f'{header}.{payload}.{sig}'


def test_valid_token():
    token = _make_token()
    assert _validate_token(token) == 'testuser'


def test_expired_token():
    token = _make_token(exp=int(time.time()) - 100)
    assert _validate_token(token) is None


def test_wrong_secret():
    token = _make_token(secret='wrong-secret')
    assert _validate_token(token) is None


def test_malformed_token():
    assert _validate_token('not.a.valid.token') is None
    assert _validate_token('') is None
    assert _validate_token('abc') is None
