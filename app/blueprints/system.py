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
