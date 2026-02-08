from flask import Blueprint, send_from_directory, current_app, jsonify

bp = Blueprint('public', __name__)

@bp.route('/')
def index():
    return send_from_directory(current_app.static_folder, 'index.html')

@bp.route('/api/ping')
def ping():
    return jsonify({'pong': True})

@bp.route('/api/routes')
def routes_list():
    return jsonify({'routes': [{'rule': r.rule, 'methods': list(r.methods)} for r in current_app.url_map.iter_rules()]})

@bp.route('/api/version')
def version():
    return jsonify({'version': '1.0.5', 'timestamp': '2026-02-08 12:00:00', 'deploy_check': 'ok'})

@bp.route('/<path:path>')
def static_proxy(path):
    # Evitar capturar prefijos de API que no hayan sido manejados por otros blueprints
    if path.startswith('api/'):
        return jsonify({'error': 'Ruta de API no válida'}), 404
    return send_from_directory(current_app.static_folder, path)
