from flask import Blueprint, send_from_directory, current_app, jsonify
import os

bp = Blueprint('public', __name__)

@bp.route('/Imagenes/<path:filename>')
def serve_images(filename):
    # Construct absolute path to Imagenes directory in project root
    # app.root_path points to '.../app'
    project_root = os.path.dirname(current_app.root_path)
    images_dir = os.path.join(project_root, 'Imagenes')
    return send_from_directory(images_dir, filename)

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
    return jsonify({'version': '1.0.8', 'timestamp': '2026-02-09 12:00:00', 'deploy_check': 'ok'})

@bp.route('/<path:path>')
def static_proxy(path):
    # Evitar capturar prefijos de API que no hayan sido manejados por otros blueprints
    if path.startswith('api/'):
        return jsonify({'error': 'Ruta de API no válida'}), 404
    return send_from_directory(current_app.static_folder, path)
