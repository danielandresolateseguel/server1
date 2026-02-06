from flask import Blueprint, request, jsonify, session, current_app
from app.database import get_db
from app.utils import is_authed, check_csrf, get_cached_tenant_config, invalidate_tenant_config
import os
import json
from datetime import datetime, timedelta

bp = Blueprint('tenants', __name__, url_prefix='/api')

def calculate_average_times(conn, slug):
    """Calcula tiempos promedio de entrega/servicio basados en historial reciente (últimos 7 días)."""
    avgs = {}
    try:
        cur = conn.cursor()
        # Mapeo config key -> (order_type, target_status)
        metrics = [
            ('time_mesa', 'mesa', 'listo'),
            ('time_espera', 'espera', 'listo'),
            ('time_delivery', 'direccion', 'entregado')
        ]
        
        limit_date = (datetime.utcnow() - timedelta(days=7)).isoformat()
        
        for cfg_key, otype, target_status in metrics:
            # Buscamos pedidos completados recientemente
            cur.execute(f"""
                SELECT o.created_at, h.changed_at 
                FROM orders o
                JOIN order_status_history h ON o.id = h.order_id
                WHERE o.tenant_slug = ? 
                  AND o.order_type = ? 
                  AND h.status = ?
                  AND o.created_at >= ?
            """, (slug, otype, target_status, limit_date))
            
            rows = cur.fetchall()
            if not rows:
                continue
                
            total_minutes = 0
            count = 0
            for r in rows:
                try:
                    start = datetime.fromisoformat(r[0])
                    end = datetime.fromisoformat(r[1])
                    diff = (end - start).total_seconds() / 60
                    if 0 < diff < 180: # Filtrar anomalías (>3h)
                        total_minutes += diff
                        count += 1
                except:
                    continue
            
            if count > 0:
                avgs[cfg_key] = int(total_minutes / count)
                
    except Exception as e:
        print(f"Error calculating average times: {e}")
        pass
        
    return avgs

@bp.route('/tenants', methods=['GET'])
def tenants():
    items = []
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT tenant_slug, config_json FROM tenant_config")
        rows = cur.fetchall()
        for r in rows:
            slug = r[0]
            try:
                j = json.loads(r[1])
            except:
                j = {}
            meta = j.get('meta') or {}
            branding = meta.get('branding') or {}
            items.append({'slug': slug, 'name': (branding.get('name') or slug)})
        conn.close()
    except Exception:
        pass
    items = sorted(items, key=lambda x: x['slug'])
    return jsonify({'tenants': items})

@bp.route('/tenant_sla', methods=['GET'])
def tenant_sla():
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    warn = 15
    crit = 30
    
    j = get_cached_tenant_config(slug)
    if j:
        sla = j.get('sla') or {}
        w = int(sla.get('warning_minutes') or warn)
        c = int(sla.get('critical_minutes') or crit)
        warn = max(1, w)
        crit = max(warn + 1, c)
        
    return jsonify({'warning_minutes': warn, 'critical_minutes': crit})

@bp.route('/tenant_sla', methods=['PATCH'])
def update_tenant_sla():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    payload = request.get_json(silent=True) or {}
    try:
        w = int(payload.get('warning_minutes'))
        c = int(payload.get('critical_minutes'))
    except Exception:
        return jsonify({'error': 'valores inválidos'}), 400
    w = max(1, w)
    c = max(w + 1, c)
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM tenant_config WHERE tenant_slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'tenant no encontrado'}), 404
        
    try:
        j = json.loads(row[0])
        sla = j.get('sla') or {}
        sla['warning_minutes'] = w
        sla['critical_minutes'] = c
        j['sla'] = sla
        
        cur.execute("UPDATE tenant_config SET config_json = ? WHERE tenant_slug = ?", (json.dumps(j), slug))
        conn.commit()
        invalidate_tenant_config(slug)
    except Exception:
        return jsonify({'error': 'no se pudo guardar configuración'}), 500
        
    return jsonify({'ok': True, 'tenant_slug': slug, 'warning_minutes': w, 'critical_minutes': c})

@bp.route('/tenant_prefs', methods=['GET'])
def tenant_prefs():
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    tip_percent = 10
    tip_default_enabled = True
    ticket_format = 'full'
    
    j = get_cached_tenant_config(slug)
    if j:
        prefs = j.get('prefs') or {}
        tperc = int(prefs.get('tip_percent') or tip_percent)
        tip_percent = max(0, min(100, tperc))
        ten = prefs.get('tip_default_enabled')
        if isinstance(ten, bool):
            tip_default_enabled = ten
        tfmt = str(prefs.get('ticket_format') or ticket_format)
        if tfmt in ('compact','full'):
            ticket_format = tfmt
            
    return jsonify({
        'tip_percent': tip_percent,
        'tip_default_enabled': tip_default_enabled,
        'ticket_format': ticket_format
    })

@bp.route('/tenant_header', methods=['GET'])
def tenant_header():
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    whatsapp = ''
    instagram = ''
    location = ''
    location_label = ''
    location_url = ''
    opening_hours = {}
    logo_url = ''
    
    j = get_cached_tenant_config(slug)
    if j:
        meta = j.get('meta') or {}
        branding = meta.get('branding') or {}
        contact = branding.get('contact') or {}
        if 'whatsapp' in contact and contact.get('whatsapp') is not None:
            whatsapp = str(contact.get('whatsapp'))
        if 'instagram' in contact and contact.get('instagram') is not None:
            instagram = str(contact.get('instagram'))
        if 'location' in contact and contact.get('location') is not None:
            location = str(contact.get('location'))
        if 'location_label' in contact and contact.get('location_label') is not None:
            location_label = str(contact.get('location_label'))
        if 'location_url' in contact and contact.get('location_url') is not None:
            location_url = str(contact.get('location_url'))
        if 'opening_hours' in contact and contact.get('opening_hours') is not None:
            oh = contact.get('opening_hours')
            if isinstance(oh, dict):
                opening_hours = oh
            else:
                try:
                    opening_hours = json.loads(oh)
                except Exception:
                    opening_hours = {}
        if 'logo_url' in contact and contact.get('logo_url') is not None:
            logo_url = str(contact.get('logo_url'))
                    
    return jsonify({
        'whatsapp': whatsapp,
        'instagram': instagram,
        'location': location,
        'location_label': location_label,
        'location_url': location_url,
        'opening_hours': opening_hours,
        'logo_url': logo_url
    })

@bp.route('/tenant_header', methods=['PATCH'])
def update_tenant_header():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    payload = request.get_json(silent=True) or {}
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM tenant_config WHERE tenant_slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'tenant no encontrado'}), 404
        
    try:
        j = json.loads(row[0])
        meta = j.get('meta') or {}
        branding = meta.get('branding') or {}
        contact = branding.get('contact') or {}
        if 'whatsapp' in payload:
            contact['whatsapp'] = str(payload.get('whatsapp') or '')
        if 'instagram' in payload:
            contact['instagram'] = str(payload.get('instagram') or '')
        if 'location' in payload:
            contact['location'] = str(payload.get('location') or '')
        if 'location_label' in payload:
            contact['location_label'] = str(payload.get('location_label') or '')
        if 'location_url' in payload:
            contact['location_url'] = str(payload.get('location_url') or '')
        if 'opening_hours' in payload:
            oh = payload.get('opening_hours')
            if isinstance(oh, dict):
                contact['opening_hours'] = oh
            else:
                try:
                    contact['opening_hours'] = json.loads(oh)
                except Exception:
                    contact['opening_hours'] = {}
        if 'logo_url' in payload:
            contact['logo_url'] = str(payload.get('logo_url') or '')
        branding['contact'] = contact
        meta['branding'] = branding
        j['meta'] = meta
        
        cur.execute("UPDATE tenant_config SET config_json = ? WHERE tenant_slug = ?", (json.dumps(j, ensure_ascii=False), slug))
        conn.commit()
        invalidate_tenant_config(slug)
    except Exception:
        return jsonify({'error': 'no se pudo guardar configuración'}), 500
        
    return jsonify({
        'ok': True,
        'tenant_slug': slug,
        'whatsapp': contact.get('whatsapp') or '',
        'instagram': contact.get('instagram') or '',
        'location': contact.get('location') or '',
        'location_label': contact.get('location_label') or '',
        'location_url': contact.get('location_url') or '',
        'opening_hours': contact.get('opening_hours') or {},
        'logo_url': contact.get('logo_url') or ''
    })

@bp.route('/tenant_checkout', methods=['PATCH'])
def update_tenant_checkout():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    payload = request.get_json(silent=True) or {}
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM tenant_config WHERE tenant_slug = ?", (slug,))
    row = cur.fetchone()
    if not row:
        return jsonify({'error': 'tenant no encontrado'}), 404
        
    try:
        j = json.loads(row[0])
        checkout = j.get('checkout') or {}
        
        if 'whatsapp_number' in payload:
            checkout['whatsappNumber'] = str(payload.get('whatsapp_number') or '')
        if 'whatsapp_enabled' in payload:
            checkout['whatsappEnabled'] = bool(payload.get('whatsapp_enabled'))
        if 'whatsapp_template' in payload:
            checkout['whatsappTemplate'] = str(payload.get('whatsapp_template') or '')
            
        j['checkout'] = checkout
        
        cur.execute("UPDATE tenant_config SET config_json = ? WHERE tenant_slug = ?", (json.dumps(j, ensure_ascii=False), slug))
        conn.commit()
        invalidate_tenant_config(slug)
    except Exception:
        return jsonify({'error': 'no se pudo guardar configuración'}), 500
        
    return jsonify({
        'ok': True,
        'tenant_slug': slug,
        'whatsapp_number': checkout.get('whatsappNumber') or '',
        'whatsapp_enabled': checkout.get('whatsappEnabled') if 'whatsappEnabled' in checkout else True,
        'whatsapp_template': checkout.get('whatsappTemplate') or ''
    })

@bp.route('/config', methods=['GET'])
def get_tenant_config():
    slug = request.args.get('slug') or 'gastronomia-local1'
    cfg = get_cached_tenant_config(slug)
    
    # Si está activado el cálculo automático, sobreescribir tiempos
    # NOTE: Calculation logic hits the DB, so we might want to cache this separately or accept the cost
    # For now, we will perform it but reuse the connection from get_db() if we were inside a view that already had it,
    # but here we need a fresh connection for calculation.
    if cfg.get('time_auto'):
        conn = get_db()
        auto_times = calculate_average_times(conn, slug)
        # Solo sobreescribir si hay datos suficientes (mayor a 0)
        # Si no hay datos, se mantiene el manual como fallback
        # Create a copy to not mutate the cached version permanently for this request
        cfg = cfg.copy()
        for k, v in auto_times.items():
            if v > 0:
                cfg[k] = v
                
    return jsonify(cfg)

@bp.route('/tenant_tables', methods=['GET'])
def get_tenant_tables():
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    j = get_cached_tenant_config(slug)
    tables = []
    if j:
        tables = j.get('tables') or []
        # Support legacy structure if needed, or default structure
        if not tables:
             tables = {'zones': [{'id': 1, 'name': 'Salón Principal', 'tables': []}]}
    
    # Ensure it returns the full object structure expected by frontend
    if isinstance(tables, list):
         # Convert legacy flat list to zones structure
         tables = {'zones': [{'id': 1, 'name': 'Salón Principal', 'tables': tables}]}
         
    return jsonify(tables)

@bp.route('/tenant_tables', methods=['POST'])
def update_tenant_tables():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    payload = request.get_json(silent=True) or {}
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM tenant_config WHERE tenant_slug = ?", (slug,))
    row = cur.fetchone()
    
    current_cfg = {}
    if row and row[0]:
        try:
            current_cfg = json.loads(row[0])
        except:
            pass
            
    # Validate payload structure slightly?
    # payload should be the 'data' object from frontend: { zones: [...] }
    if not isinstance(payload, dict) or 'zones' not in payload:
         return jsonify({'error': 'formato inválido'}), 400
         
    current_cfg['tables'] = payload
    
    try:
        cur.execute("INSERT OR REPLACE INTO tenant_config (tenant_slug, config_json) VALUES (?, ?)", (slug, json.dumps(current_cfg, ensure_ascii=False)))
        conn.commit()
        invalidate_tenant_config(slug)
    except Exception as e:
        print(f"Error saving tables: {e}")
        return jsonify({'error': 'error al guardar'}), 500
        
    return jsonify({'ok': True})

@bp.route('/config', methods=['POST'])
def update_tenant_config():
    if not is_authed(): return jsonify({'error': 'unauthorized'}), 401
    payload = request.get_json(silent=True) or {}
    slug = payload.get('slug') or 'gastronomia-local1'
    
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT config_json FROM tenant_config WHERE tenant_slug = ?", (slug,))
    row = cur.fetchone()
    current_cfg = {}
    if row and row[0]:
        try:
            current_cfg = json.loads(row[0])
        except:
            pass
    
    # Update known keys
    if 'shipping_cost' in payload:
        try:
            current_cfg['shipping_cost'] = int(payload['shipping_cost'])
        except Exception: pass
            
    if 'time_mesa' in payload:
        try:
            current_cfg['time_mesa'] = int(payload['time_mesa'])
        except Exception: pass
            
    if 'time_espera' in payload:
        try:
            current_cfg['time_espera'] = int(payload['time_espera'])
        except Exception: pass
            
    if 'time_delivery' in payload:
        try:
            current_cfg['time_delivery'] = int(payload['time_delivery'])
        except Exception: pass
            
    if 'time_auto' in payload:
        current_cfg['time_auto'] = bool(payload['time_auto'])
    
    cur.execute("INSERT OR REPLACE INTO tenant_config (tenant_slug, config_json) VALUES (?, ?)", (slug, json.dumps(current_cfg)))
    conn.commit()
    invalidate_tenant_config(slug)
    return jsonify(current_cfg)

