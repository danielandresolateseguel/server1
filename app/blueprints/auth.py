import secrets
from flask import Blueprint, request, jsonify, session
from werkzeug.security import check_password_hash, generate_password_hash
from app.database import get_db
from app.utils import is_authed, check_csrf, get_csrf_token

bp = Blueprint('auth', __name__, url_prefix='/api')

@bp.route('/auth/login', methods=['POST'])
def auth_login():
    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username') or '')
    password = str(payload.get('password') or '')
    tenant_slug = str(payload.get('tenant_slug') or '')
    if not username or not password or not tenant_slug:
        return jsonify({'error': 'credenciales incompletas'}), 400
    
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT password_hash FROM admin_users WHERE tenant_slug = ? AND username = ?", (tenant_slug, username))
    row = cur.fetchone()
    
    if not row or not check_password_hash(row[0], password):
        return jsonify({'error': 'usuario o contraseña inválidos'}), 401
    
    session['admin_auth'] = True
    session['admin_user'] = username
    session['tenant_slug'] = tenant_slug
    session['csrf_token'] = secrets.token_urlsafe(32)
    return jsonify({'ok': True, 'tenant_slug': tenant_slug})

@bp.route('/auth/login_dev', methods=['POST'])
def auth_login_dev():
    payload = request.get_json(silent=True) or {}
    u = str(payload.get('username') or '')
    t = str(payload.get('tenant_slug') or '')
    session['admin_auth'] = True
    session['admin_user'] = u or 'admin'
    if t:
        session['tenant_slug'] = t
    session['csrf_token'] = secrets.token_urlsafe(32)
    return jsonify({'ok': True, 'dev': True, 'tenant_slug': t or None})

@bp.route('/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'ok': True})

@bp.route('/auth/me', methods=['GET'])
def auth_me():
    return jsonify({'authenticated': is_authed(), 'user': session.get('admin_user') or '', 'tenant_slug': session.get('tenant_slug') or ''})

@bp.route('/auth/csrf', methods=['GET'])
def auth_csrf():
    # Allow fetching CSRF token even if not authenticated (for login page, etc)
    return jsonify({'token': get_csrf_token()})

@bp.route('/admin_users', methods=['GET'])
def admin_users_list():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    tenant_slug = request.args.get('tenant_slug') or session.get('tenant_slug') or ''
    if session.get('tenant_slug') and tenant_slug and session.get('tenant_slug') != tenant_slug:
        return jsonify({'error': 'acceso denegado al tenant'}), 403
    
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT username FROM admin_users WHERE tenant_slug = ? ORDER BY username ASC", (tenant_slug,))
    rows = cur.fetchall()
    
    return jsonify({'tenant_slug': tenant_slug, 'users': [r[0] for r in rows]})

@bp.route('/admin_users', methods=['POST'])
def admin_users_create():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    username = str(payload.get('username') or '').strip()
    password = str(payload.get('password') or '')
    tenant_slug = str(payload.get('tenant_slug') or session.get('tenant_slug') or '').strip()
    if not username or not password or not tenant_slug:
        return jsonify({'error': 'datos incompletos'}), 400
    if session.get('tenant_slug') and session.get('tenant_slug') != tenant_slug:
        return jsonify({'error': 'acceso denegado al tenant'}), 403
    
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT 1 FROM admin_users WHERE tenant_slug = ? AND username = ?", (tenant_slug, username))
    exists = cur.fetchone()
    if exists:
        return jsonify({'error': 'usuario ya existe'}), 409
    
    ph = generate_password_hash(password)
    cur.execute("INSERT INTO admin_users (tenant_slug, username, password_hash) VALUES (?, ?, ?)", (tenant_slug, username, ph))
    db.commit()
    
    return jsonify({'ok': True, 'username': username, 'tenant_slug': tenant_slug})
