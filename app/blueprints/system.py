from flask import Blueprint, jsonify, current_app
import os
import sys

bp = Blueprint('system', __name__)

@bp.route('/api/version')
def version():
    return jsonify({
        'version': '1.0.6', 
        'timestamp': '2026-02-08 12:30:00', 
        'deploy_check': 'ok',
        'python_version': sys.version,
        'cwd': os.getcwd()
    })

@bp.route('/api/ping_system')
def ping():
    return jsonify({'status': 'ok', 'message': 'System blueprint active'})

@bp.route('/api/routes_debug')
def routes_debug():
    routes = []
    for rule in current_app.url_map.iter_rules():
        routes.append(f"{rule.endpoint}: {rule.rule} ({','.join(rule.methods)})")
    return jsonify({'routes': routes})

@bp.route('/api/db_check')
def db_check():
    import os
    from app.database import get_db
    
    status = {
        'database_url_configured': bool(os.environ.get('DATABASE_URL')),
        'is_postgres': False,
        'connection_success': False,
        'tables': [],
        'admin_users_count': 0,
        'error': None
    }
    
    # Check URL masking
    db_url = os.environ.get('DATABASE_URL', '')
    if db_url:
        # Mask password
        try:
            parts = db_url.split('@')
            if len(parts) > 1:
                status['masked_url'] = '...' + parts[1]
            else:
                status['masked_url'] = 'Invalid format'
        except:
            status['masked_url'] = 'Error masking'
            
    try:
        db = get_db()
        status['is_postgres'] = current_app.config.get('IS_POSTGRES', False)
        
        cur = db.cursor()
        cur.execute("SELECT 1")
        status['connection_success'] = True
        
        # List tables
        if status['is_postgres']:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
        else:
            cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
            
        rows = cur.fetchall()
        status['tables'] = [r[0] for r in rows]
        
        # Check users
        if 'admin_users' in status['tables']:
            cur.execute("SELECT COUNT(*) FROM admin_users")
            res = cur.fetchone()
            status['admin_users_count'] = res[0] if res else 0
            
    except Exception as e:
        status['error'] = str(e)
        
    return jsonify(status)
