from flask import Blueprint, request, jsonify, session
from app.database import get_db
from app.utils import is_authed, check_csrf
from datetime import datetime

bp = Blueprint('carousel', __name__, url_prefix='/api/carousel')

@bp.route('', methods=['GET'])
def list_carousel_slides():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM carousel_slides WHERE tenant_slug = ? ORDER BY position ASC, id ASC",
        (tenant_slug,)
    )
    rows = cur.fetchall()
    return jsonify({'slides': [dict(r) for r in rows]})

@bp.route('', methods=['POST'])
def create_carousel_slide():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    if session.get('tenant_slug') and session.get('tenant_slug') != tenant_slug:
        return jsonify({'error': 'acceso denegado al tenant'}), 403
        
    payload = request.get_json(silent=True) or {}
    image_url = payload.get('image_url')
    if not image_url:
        return jsonify({'error': 'image_url requerida'}), 400
        
    title = payload.get('title') or ''
    text = payload.get('text') or ''
    title_color = payload.get('title_color') or ''
    text_color = payload.get('text_color') or ''
    position = int(payload.get('position') or 0)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO carousel_slides (tenant_slug, image_url, title, text, position, active, created_at, title_color, text_color) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
        (tenant_slug, image_url, title, text, position, datetime.utcnow().isoformat(), title_color, text_color)
    )
    new_id = cur.lastrowid
    conn.commit()
    return jsonify({'ok': True, 'id': new_id})

@bp.route('/<int:slide_id>', methods=['PATCH'])
def update_carousel_slide(slide_id):
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
        
    payload = request.get_json(silent=True) or {}
    fields = []
    params = []
    
    if 'image_url' in payload:
        fields.append('image_url = ?')
        params.append(payload['image_url'])
    if 'title' in payload:
        fields.append('title = ?')
        params.append(payload['title'])
    if 'text' in payload:
        fields.append('text = ?')
        params.append(payload['text'])
    if 'title_color' in payload:
        fields.append('title_color = ?')
        params.append(payload['title_color'])
    if 'text_color' in payload:
        fields.append('text_color = ?')
        params.append(payload['text_color'])
    if 'position' in payload:
        try:
            fields.append('position = ?')
            params.append(int(payload['position']))
        except: pass
    if 'active' in payload:
        try:
            fields.append('active = ?')
            params.append(1 if payload['active'] else 0)
        except: pass
        
    if not fields:
        return jsonify({'error': 'sin cambios'}), 400
        
    params.append(slide_id)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE carousel_slides SET {', '.join(fields)} WHERE id = ?", params)
    conn.commit()
    return jsonify({'ok': True})

@bp.route('/<int:slide_id>', methods=['DELETE'])
def delete_carousel_slide(slide_id):
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
        
    conn = get_db()
    cur = conn.cursor()
    cur.execute("DELETE FROM carousel_slides WHERE id = ?", (slide_id,))
    conn.commit()
    return jsonify({'ok': True})
