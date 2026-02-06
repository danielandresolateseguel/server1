import secrets
import time
import json
from flask import session, request
from app.database import get_db

# Simple in-memory cache: {slug: (config_dict, timestamp)}
_config_cache = {}
CACHE_TTL = 300  # 5 minutes

def get_cached_tenant_config(slug):
    now = time.time()
    if slug in _config_cache:
        data, ts = _config_cache[slug]
        if now - ts < CACHE_TTL:
            return data
            
    # Fetch from DB
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT config_json FROM tenant_config WHERE tenant_slug = ?", (slug,))
        row = cur.fetchone()
        if row and row[0]:
            try:
                cfg = json.loads(row[0])
                _config_cache[slug] = (cfg, now)
                return cfg
            except:
                pass
    except Exception as e:
        print(f"Error fetching config for {slug}: {e}")
        
    return {}

def invalidate_tenant_config(slug):
    if slug in _config_cache:
        del _config_cache[slug]

def is_authed():
    return bool(session.get('admin_auth'))


def get_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token

def check_csrf():
    token = request.headers.get('X-CSRF-Token') or request.headers.get('X-CSRFToken')
    return token and token == session.get('csrf_token')
