import os
import sqlite3
import argparse
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session
import secrets
import unicodedata
from werkzeug.security import check_password_hash
import threading
import time

# Directorio base del proyecto
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DEFAULT_PORT = 8000

parser = argparse.ArgumentParser(description="Servidor Flask para el proyecto (API + estáticos)")
parser.add_argument("-p", "--port", type=int, help="Puerto de escucha (1-65535)")
args = parser.parse_args()

env_port = os.environ.get("PORT")

def resolve_port(cli_port, env_port_value, default):
    if cli_port is not None and 1 <= cli_port <= 65535:
        return cli_port
    if env_port_value:
        try:
            parsed = int(env_port_value)
            if 1 <= parsed <= 65535:
                return parsed
        except ValueError:
            print(f"Advertencia: PORT='{env_port_value}' no es un número válido. Usando puerto por defecto {default}.")
    return default

PORT = resolve_port(args.port, env_port, DEFAULT_PORT)

# --- Inicialización de base de datos (SQLite) ---
DB_PATH = os.path.join(BASE_DIR, 'orders.db')
CONFIG_DIR = os.path.join(BASE_DIR, 'config')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    # Tabla de pedidos
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug TEXT NOT NULL,
            customer_name TEXT,
            customer_phone TEXT,
            order_type TEXT NOT NULL,
            table_number TEXT,
            address_json TEXT,
            status TEXT NOT NULL,
            total INTEGER NOT NULL,
            payment_method TEXT,
            payment_status TEXT,
            created_at TEXT NOT NULL,
            order_notes TEXT
        )
        """
    )
    try:
        cur.execute("SELECT name FROM pragma_table_info('orders') WHERE name = 'order_notes'")
        row = cur.fetchone()
        if not row:
            cur.execute("ALTER TABLE orders ADD COLUMN order_notes TEXT")
    except Exception:
        pass
    # Ítems del pedido
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS order_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            tenant_slug TEXT NOT NULL,
            product_id TEXT,
            name TEXT NOT NULL,
            qty INTEGER NOT NULL,
            unit_price INTEGER NOT NULL,
            modifiers_json TEXT,
            notes TEXT,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
        """
    )
    # Índices básicos
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_tenant_status ON orders(tenant_slug, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at)")
    # Historial de cambios de estado
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS order_status_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            status TEXT NOT NULL,
            changed_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_order_history_order ON order_status_history(order_id)")
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS archived_orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            tenant_slug TEXT NOT NULL,
            type TEXT NOT NULL,
            archived_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
        """
    )
    cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_archived_unique ON archived_orders(order_id, type)")
    conn.commit()
    conn.close()

# --- Aplicación Flask ---
app = Flask(__name__, static_folder=BASE_DIR, static_url_path='')
app.secret_key = os.environ.get('FLASK_SECRET_KEY') or os.urandom(32)
app.config.update({
    'SESSION_COOKIE_HTTPONLY': True,
    'SESSION_COOKIE_SAMESITE': 'Lax',
    'SESSION_COOKIE_SECURE': bool(os.environ.get('COOKIE_SECURE')),
})

def is_authed():
    return bool(session.get('admin_auth'))

def get_csrf_token():
    token = session.get('csrf_token')
    if not token:
        token = secrets.token_urlsafe(32)
        session['csrf_token'] = token
    return token

def check_csrf():
    token = request.headers.get('X-CSRF-Token')
    return token and token == session.get('csrf_token')

@app.route('/')
def root():
    # Servir página principal por defecto
    return send_from_directory(BASE_DIR, 'index.html')

def compute_total(items):
    total = 0
    for it in items:
        try:
            price = int(it.get('price', 0))
            qty = int(it.get('quantity', it.get('qty', 1)))
        except Exception:
            price, qty = 0, 0
        total += max(0, price) * max(0, qty)
    return total

@app.route('/api/orders', methods=['POST'])
def create_order():
    payload = request.get_json(silent=True) or {}
    # Slug por recomendación del usuario: usar exactamente "gastronomia-local1" como default
    tenant_slug = payload.get('tenant_slug') or payload.get('slug') or 'gastronomia-local1'
    order_type = (payload.get('order_type') or 'mesa').lower()
    if order_type not in ('mesa', 'direccion', 'none'):
        return jsonify({'error': 'order_type inválido'}), 400
    table_number = payload.get('table_number') or ''
    address_json = payload.get('address') or {}
    items = payload.get('items') or []
    customer_name = payload.get('customer_name') or ''
    customer_phone = payload.get('customer_phone') or ''

    # Reglas simples de validación
    if order_type == 'mesa' and not table_number:
        return jsonify({'error': 'Número de mesa requerido'}), 400
    if order_type == 'direccion' and not address_json:
        return jsonify({'error': 'Dirección requerida'}), 400
    if not items:
        return jsonify({'error': 'Carrito vacío'}), 400

    total = compute_total(items)
    created_at = datetime.utcnow().isoformat()
    status = 'pendiente'

    conn = get_db()
    cur = conn.cursor()
    order_notes = (payload.get('order_notes') or '').strip()
    cur.execute(
        """
        INSERT INTO orders (tenant_slug, customer_name, customer_phone, order_type, table_number, address_json, status, total, payment_method, payment_status, created_at, order_notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (tenant_slug, customer_name, customer_phone, order_type, table_number, str(address_json), status, total, None, None, created_at, order_notes)
    )
    order_id = cur.lastrowid
    # Insertar ítems
    for it in items:
        cur.execute(
            """
            INSERT INTO order_items (order_id, tenant_slug, product_id, name, qty, unit_price, modifiers_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                tenant_slug,
                it.get('id'),
                it.get('name'),
                int(it.get('quantity', it.get('qty', 1)) or 1),
                int(it.get('price', 0) or 0),
                str(it.get('modifiers') or {}),
                it.get('notes') or ''
            )
        )
    conn.commit()
    conn.close()
    # Registrar historial inicial
    try:
        conn2 = get_db()
        cur2 = conn2.cursor()
        cur2.execute(
            "INSERT INTO order_status_history (order_id, status, changed_at) VALUES (?, ?, ?)",
            (order_id, status, created_at)
        )
        conn2.commit()
    finally:
        conn2.close()

    return jsonify({'order_id': order_id, 'status': status, 'total': total, 'tenant_slug': tenant_slug}), 201

@app.route('/api/orders', methods=['GET'])
def list_orders():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    status = request.args.get('status')
    limit = int(request.args.get('limit') or 50)
    offset = int(request.args.get('offset') or 0)
    q = request.args.get('q')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    conn = get_db()
    cur = conn.cursor()
    base = "SELECT id, tenant_slug, order_type, table_number, address_json, status, total, created_at, customer_phone FROM orders WHERE tenant_slug = ?"
    params = [tenant_slug]
    if status:
        base += " AND status = ?"
        params.append(status)
    if q:
        # Búsqueda por ID exacto si numérica, o texto en varios campos
        try:
            qid = int(q)
            base += " AND id = ?"
            params.append(qid)
        except Exception:
            like = f"%{q}%"
            base += " AND (COALESCE(address_json,'') LIKE ? OR COALESCE(customer_name,'') LIKE ? OR COALESCE(customer_phone,'') LIKE ? OR COALESCE(table_number,'') LIKE ?)"
            params.extend([like, like, like, like])
    if from_date:
        base += " AND created_at >= ?"
        params.append(from_date)
    if to_date:
        base += " AND created_at <= ?"
        params.append(to_date)
    base += " ORDER BY id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(base, params)
    rows = cur.fetchall()
    data = [dict(r) for r in rows]
    # Obtener total para paginación rápida
    cur.execute("SELECT COUNT(*) as c FROM orders WHERE tenant_slug = ?" + (" AND status = ?" if status else ""), [tenant_slug] + ([status] if status else []))
    total_count = cur.fetchone()[0]
    conn.close()
    return jsonify({'orders': data, 'count': len(data), 'total': total_count, 'limit': limit, 'offset': offset})

@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status')
    if new_status not in ('pendiente', 'preparacion', 'listo', 'en_camino', 'entregado', 'cancelado'):
        return jsonify({'error': 'status inválido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    # Registrar historial
    cur.execute("INSERT INTO order_status_history (order_id, status, changed_at) VALUES (?, ?, ?)", (order_id, new_status, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return jsonify({'order_id': order_id, 'status': new_status})

@app.route('/api/orders/<int:order_id>', methods=['GET'])
def get_order_detail(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, tenant_slug, customer_name, customer_phone, order_type, table_number, address_json, status, total, payment_method, payment_status, created_at, order_notes
        FROM orders WHERE id = ?
        """,
        (order_id,)
    )
    order_row = cur.fetchone()
    if not order_row:
        conn.close()
        return jsonify({'error': 'Orden no encontrada'}), 404
    cur.execute(
        """
        SELECT id, product_id, name, qty, unit_price, modifiers_json, notes
        FROM order_items WHERE order_id = ? ORDER BY id ASC
        """,
        (order_id,)
    )
    item_rows = cur.fetchall()
    # Historial
    cur.execute(
        """
        SELECT status, changed_at FROM order_status_history WHERE order_id = ? ORDER BY id ASC
        """,
        (order_id,)
    )
    hist_rows = cur.fetchall()
    conn.close()
    order = dict(order_row)
    items = [dict(r) for r in item_rows]
    history = [dict(r) for r in hist_rows]
    return jsonify({'order': order, 'items': items, 'history': history})

@app.route('/api/orders/export.csv', methods=['GET'])
def export_orders_csv():
    if not is_authed():
        from flask import Response
        return Response('unauthorized', status=401)
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    status = request.args.get('status')
    q = request.args.get('q')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    conn = get_db()
    cur = conn.cursor()
    base = "SELECT id, created_at, order_type, table_number, address_json, total, status, customer_phone FROM orders WHERE tenant_slug = ?"
    params = [tenant_slug]
    if status:
        base += " AND status = ?"
        params.append(status)
    if q:
        try:
            qid = int(q)
            base += " AND id = ?"
            params.append(qid)
        except Exception:
            like = f"%{q}%"
            base += " AND (COALESCE(address_json,'') LIKE ? OR COALESCE(customer_name,'') LIKE ? OR COALESCE(customer_phone,'') LIKE ? OR COALESCE(table_number,'') LIKE ?)"
            params.extend([like, like, like, like])
    if from_date:
        base += " AND created_at >= ?"
        params.append(from_date)
    if to_date:
        base += " AND created_at <= ?"
        params.append(to_date)
    base += " ORDER BY id DESC"
    cur.execute(base, params)
    rows = cur.fetchall()
    conn.close()
    # Construir CSV
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "order_type", "destination", "customer_phone", "total", "tip_10_percent", "total_with_tip", "status"])
    for r in rows:
        dest = r[3] if r[2] == 'mesa' else (r[4] or '')
        total = int(r[5] or 0)
        # Propina 10% con redondeo "half up" para coincidir con Math.round
        tip = (total + 5) // 10
        total_with_tip = total + tip
        phone = r[7] or ''
        writer.writerow([r[0], r[1], r[2], dest, phone, total, tip, total_with_tip, r[6]])
    resp = output.getvalue()
    from flask import Response
    return Response(resp, mimetype='text/csv', headers={'Content-Disposition': 'attachment; filename="orders_export.csv"'})

@app.route('/api/archive', methods=['GET'])
def get_archive():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    a_type = request.args.get('type')
    limit = int(request.args.get('limit') or 100)
    offset = int(request.args.get('offset') or 0)
    q = request.args.get('q')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    date_field = (request.args.get('date_field') or 'archived').strip().lower()
    if date_field not in ('archived', 'order'):
        date_field = 'archived'
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10:
                return s + ('T23:59:59' if end else 'T00:00:00')
        except Exception:
            pass
        return s
    from_date = _norm_date(from_date, end=False)
    to_date = _norm_date(to_date, end=True)
    conn = get_db()
    cur = conn.cursor()
    base = """
        SELECT o.id, o.created_at, o.order_type, o.table_number, o.address_json, o.total, o.status, o.customer_name, o.customer_phone, h.last_status, h.last_change
        FROM archived_orders a
        JOIN orders o ON o.id = a.order_id
        LEFT JOIN (
          SELECT x.order_id, x.status AS last_status, x.changed_at AS last_change
          FROM order_status_history x
          JOIN (
            SELECT order_id, MAX(changed_at) AS mc FROM order_status_history GROUP BY order_id
          ) y ON y.order_id = x.order_id AND y.mc = x.changed_at
        ) h ON h.order_id = o.id
        WHERE a.tenant_slug = ?
    """
    params = [tenant_slug]
    if a_type:
        base += " AND a.type = ?"
        params.append(a_type)
    date_col = 'a.archived_at' if date_field == 'archived' else 'o.created_at'
    if from_date:
        base += f" AND {date_col} >= ?"
        params.append(from_date)
    if to_date:
        base += f" AND {date_col} <= ?"
        params.append(to_date)
    if q:
        try:
            qid = int(q)
            base += " AND o.id = ?"
            params.append(qid)
        except Exception:
            nq = __import__('re').sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=__import__('re').IGNORECASE).strip()
            like = f"%{nq.lower()}%"
            base += " AND (LOWER(COALESCE(o.address_json,'')) LIKE ? OR LOWER(COALESCE(o.table_number,'')) LIKE ? OR LOWER(COALESCE(o.customer_name,'')) LIKE ?)"
            params.extend([like, like, like])
    base += " ORDER BY o.id DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(base, params)
    rows = cur.fetchall()
    # total_count
    count_sql = """
        SELECT COUNT(*)
        FROM archived_orders a
        JOIN orders o ON o.id = a.order_id
        LEFT JOIN (
          SELECT x.order_id, x.status AS last_status, x.changed_at AS last_change
          FROM order_status_history x
          JOIN (
            SELECT order_id, MAX(changed_at) AS mc FROM order_status_history GROUP BY order_id
          ) y ON y.order_id = x.order_id AND y.mc = x.changed_at
        ) h ON h.order_id = o.id
        WHERE a.tenant_slug = ?
    """
    count_params = [tenant_slug]
    if a_type:
        count_sql += " AND a.type = ?"
        count_params.append(a_type)
    date_col = 'a.archived_at' if date_field == 'archived' else 'o.created_at'
    if from_date:
        count_sql += f" AND {date_col} >= ?"
        count_params.append(from_date)
    if to_date:
        count_sql += f" AND {date_col} <= ?"
        count_params.append(to_date)
    if q:
        try:
            qid = int(q)
            count_sql += " AND o.id = ?"
            count_params.append(qid)
        except Exception:
            nq = __import__('re').sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=__import__('re').IGNORECASE).strip()
            like = f"%{nq.lower()}%"
            count_sql += " AND (LOWER(COALESCE(o.address_json,'')) LIKE ? OR LOWER(COALESCE(o.table_number,'')) LIKE ? OR LOWER(COALESCE(o.customer_name,'')) LIKE ?)"
            count_params.extend([like, like, like])
    cur.execute(count_sql, count_params)
    total_count = int(cur.fetchone()[0])
    conn.close()
    data = [dict(r) for r in rows]
    if q:
        try:
            int(q)
        except Exception:
            def _norm(s):
                s = str(s or '').lower()
                return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
            nq = __import__('re').sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=__import__('re').IGNORECASE).strip()
            nq = _norm(nq)
            data = [r for r in data if (nq in _norm(r.get('address_json')) or nq in _norm(r.get('table_number')) or nq in _norm(r.get('customer_name')))]
    return jsonify({'archives': data, 'count': len(data), 'limit': limit, 'offset': offset, 'total_count': total_count})

@app.route('/api/archive/eligible_count', methods=['GET'])
def archive_eligible_count():
    a_type = request.args.get('type')
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or ''
    hours = int(request.args.get('hours') or 24)
    if a_type not in ('delivered','canceled'):
        return jsonify({'error': 'type inválido'}), 400
    cutoff_dt = datetime.utcnow() - timedelta(hours=max(1, hours))
    cutoff = cutoff_dt.isoformat()
    conn = get_db()
    cur = conn.cursor()
    base_status = 'entregado' if a_type == 'delivered' else 'cancelado'
    sql = """
        SELECT COUNT(*)
        FROM orders o
        JOIN (
          SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = ? GROUP BY order_id
        ) h ON h.order_id = o.id
        LEFT JOIN archived_orders a ON a.order_id = o.id AND a.type = ?
        WHERE a.order_id IS NULL AND h.last_change <= ?
    """
    params = [base_status, a_type, cutoff]
    if tenant_slug:
        sql += " AND o.tenant_slug = ?"
        params.append(tenant_slug)
    cur.execute(sql, params)
    n = cur.fetchone()[0]
    conn.close()
    return jsonify({'count': int(n), 'type': a_type, 'tenant_slug': tenant_slug or None, 'hours': hours})

@app.route('/api/archive/export.csv', methods=['GET'])
@app.route('/api/archive/export', methods=['GET'])
def archive_export():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    a_type = request.args.get('type')
    q = request.args.get('q')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    date_field = (request.args.get('date_field') or 'archived').strip().lower()
    if date_field not in ('archived', 'order'):
        date_field = 'archived'
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10:
                return s + ('T23:59:59' if end else 'T00:00:00')
        except Exception:
            pass
        return s
    from_date = _norm_date(from_date, end=False)
    to_date = _norm_date(to_date, end=True)
    conn = get_db()
    cur = conn.cursor()
    base = """
        SELECT o.id, o.created_at, o.order_type, o.table_number, o.address_json, o.total, o.status, a.archived_at, o.customer_name, o.customer_phone, h.last_status, h.last_change
        FROM archived_orders a
        JOIN orders o ON o.id = a.order_id
        LEFT JOIN (
          SELECT x.order_id, x.status AS last_status, x.changed_at AS last_change
          FROM order_status_history x
          JOIN (
            SELECT order_id, MAX(changed_at) AS mc FROM order_status_history GROUP BY order_id
          ) y ON y.order_id = x.order_id AND y.mc = x.changed_at
        ) h ON h.order_id = o.id
        WHERE a.tenant_slug = ?
    """
    params = [tenant_slug]
    if a_type:
        base += " AND a.type = ?"
        params.append(a_type)
    date_col = 'a.archived_at' if date_field == 'archived' else 'o.created_at'
    if from_date:
        base += f" AND {date_col} >= ?"
        params.append(from_date)
    if to_date:
        base += f" AND {date_col} <= ?"
        params.append(to_date)
    if q:
        try:
            qid = int(q)
            base += " AND o.id = ?"
            params.append(qid)
        except Exception:
            nq = __import__('re').sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=__import__('re').IGNORECASE).strip()
            like = f"%{nq.lower()}%"
            base += " AND (LOWER(COALESCE(o.address_json,'')) LIKE ? OR LOWER(COALESCE(o.table_number,'')) LIKE ? OR LOWER(COALESCE(o.customer_name,'')) LIKE ?)"
            params.extend([like, like, like])
    base += " ORDER BY o.id DESC"
    cur.execute(base, params)
    rows = cur.fetchall()
    import csv
    from io import StringIO
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "order_type", "destination", "customer_phone", "total", "status", "archived_at", "customer_name", "last_status", "last_change"])
    for r in rows:
        dest = r[3] if r[2] == 'mesa' else (r[4] or '')
        total = int(r[5] or 0)
        writer.writerow([r[0], r[1], r[2], dest, r[9] or '', total, r[6], r[7], r[8], r[10] or '', r[11] or ''])
    resp = output.getvalue()
    from flask import Response
    def _safe(s):
        return ''.join(c for c in str(s or '') if c.isalnum() or c in ('-', '_'))
    df = 'arch' if date_field == 'archived' else 'order'
    def _dpart(d):
        try:
            return str(d or 'all')[:10].replace('T','').replace(':','')
        except Exception:
            return 'all'
    fname = f"archives_{_safe(tenant_slug or 'tenant')}_{df}_{_dpart(from_date)}_{_dpart(to_date)}_{_safe(a_type or 'all')}.csv"
    return Response(resp, mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename="{fname}"'})

@app.route('/api/archive/metrics', methods=['GET'])
def archive_metrics():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    date_field = (request.args.get('date_field') or 'archived').strip().lower()
    if date_field not in ('archived', 'order'):
        date_field = 'archived'
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10:
                return s + ('T23:59:59' if end else 'T00:00:00')
        except Exception:
            pass
        return s
    from_date = _norm_date(from_date, end=False)
    to_date = _norm_date(to_date, end=True)
    conn = get_db()
    cur = conn.cursor()
    date_col = 'a.archived_at' if date_field == 'archived' else 'o.created_at'
    base = f"""
        SELECT o.total
        FROM archived_orders a JOIN orders o ON o.id = a.order_id
        WHERE a.tenant_slug = ? AND a.type = ?
        {" AND " + date_col + " >= ?" if from_date else ''}
        {" AND " + date_col + " <= ?" if to_date else ''}
    """
    # Delivered metrics
    params_del = [tenant_slug, 'delivered'] + ([from_date] if from_date else []) + ([to_date] if to_date else [])
    cur.execute(base, params_del)
    rows_del = cur.fetchall()
    delivered_count = len(rows_del)
    delivered_total = int(sum(int(r[0] or 0) for r in rows_del))
    tip = (delivered_total + 5) // 10
    delivered_total_with_tip = delivered_total + tip
    # Canceled metrics
    params_can = [tenant_slug, 'canceled'] + ([from_date] if from_date else []) + ([to_date] if to_date else [])
    cur.execute(base, params_can)
    rows_can = cur.fetchall()
    canceled_count = len(rows_can)
    canceled_total = int(sum(int(r[0] or 0) for r in rows_can))
    conn.close()
    return jsonify({
        'delivered_count': delivered_count,
        'delivered_total': delivered_total,
        'delivered_tip_10': tip,
        'delivered_total_with_tip': delivered_total_with_tip,
        'canceled_count': canceled_count,
        'canceled_total': canceled_total
    })

@app.route('/api/archive', methods=['POST'])
def post_archive():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    order_id = payload.get('order_id')
    a_type = payload.get('type')
    if not isinstance(order_id, int):
        try:
            order_id = int(order_id)
        except Exception:
            return jsonify({'error': 'order_id inválido'}), 400
    if a_type not in ('delivered', 'canceled'):
        return jsonify({'error': 'type inválido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, tenant_slug, status FROM orders WHERE id = ?", (order_id,))
    r = cur.fetchone()
    if not r:
        conn.close()
        return jsonify({'error': 'orden no encontrada'}), 404
    tenant_slug = r[1]
    cur.execute(
        "INSERT OR IGNORE INTO archived_orders (order_id, tenant_slug, type, archived_at) VALUES (?, ?, ?, ?)",
        (order_id, tenant_slug, a_type, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'order_id': order_id, 'type': a_type})

def _auto_archive_once():
    try:
        conn = get_db()
        cur = conn.cursor()
        cutoff_dt = datetime.utcnow() - timedelta(hours=24)
        cutoff = cutoff_dt.isoformat()
        cur.execute(
            """
            SELECT o.id, o.tenant_slug
            FROM orders o
            JOIN (
              SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id
            ) h ON h.order_id = o.id
            LEFT JOIN archived_orders a ON a.order_id = o.id AND a.type = 'delivered'
            WHERE a.order_id IS NULL AND h.last_change <= ?
            """,
            (cutoff,)
        )
        rows_del = cur.fetchall()
        for r in rows_del:
            oid = r[0]
            slug = r[1]
            cur.execute(
                "INSERT OR IGNORE INTO archived_orders (order_id, tenant_slug, type, archived_at) VALUES (?, ?, 'delivered', ?)",
                (oid, slug, cutoff)
            )
        cur.execute(
            """
            SELECT o.id, o.tenant_slug
            FROM orders o
            JOIN (
              SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'cancelado' GROUP BY order_id
            ) h ON h.order_id = o.id
            LEFT JOIN archived_orders a ON a.order_id = o.id AND a.type = 'canceled'
            WHERE a.order_id IS NULL AND h.last_change <= ?
            """,
            (cutoff,)
        )
        rows_can = cur.fetchall()
        for r in rows_can:
            oid = r[0]
            slug = r[1]
            cur.execute(
                "INSERT OR IGNORE INTO archived_orders (order_id, tenant_slug, type, archived_at) VALUES (?, ?, 'canceled', ?)",
                (oid, slug, cutoff)
            )
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

def start_background_tasks():
    if getattr(app, '_bg_started', False):
        return
    app._bg_started = True
    def loop():
        while True:
            try:
                _auto_archive_once()
            except Exception:
                pass
            time.sleep(300)
    t = threading.Thread(target=loop, daemon=True)
    t.start()

@app.route('/api/metrics', methods=['GET'])
def metrics():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM orders WHERE tenant_slug = ? AND status NOT IN ('entregado','cancelado')", (tenant_slug,))
    active_count = cur.fetchone()[0]
    params = [tenant_slug]
    delivered_where = "status = 'entregado' AND order_id IN (SELECT id FROM orders WHERE tenant_slug = ?)"
    canceled_where = "status = 'cancelado' AND order_id IN (SELECT id FROM orders WHERE tenant_slug = ?)"
    if from_date:
        delivered_where += " AND changed_at >= ?"
        canceled_where += " AND changed_at >= ?"
        params.append(from_date)
        params.append(from_date)
    if to_date:
        delivered_where += " AND changed_at <= ?"
        canceled_where += " AND changed_at <= ?"
        params.append(to_date)
        params.append(to_date)
    cur.execute(f"SELECT COUNT(*) FROM order_status_history WHERE {delivered_where}", params[:(2 + (1 if from_date else 0) + (1 if to_date else 0))])
    delivered_count = cur.fetchone()[0]
    cur.execute(f"SELECT COUNT(*) FROM order_status_history WHERE {canceled_where}", params[(2 + (1 if from_date else 0) + (1 if to_date else 0)):])
    canceled_count = cur.fetchone()[0]
    cur.execute(
        """
        SELECT COALESCE(SUM(o.total),0) FROM orders o
        JOIN order_status_history h ON h.order_id = o.id
        WHERE o.tenant_slug = ? AND h.status = 'entregado'
        """ + (" AND h.changed_at >= ?" if from_date else "") + (" AND h.changed_at <= ?" if to_date else ""),
        [tenant_slug] + ([from_date] if from_date else []) + ([to_date] if to_date else [])
    )
    delivered_total = int(cur.fetchone()[0] or 0)
    tip = (delivered_total + 5) // 10
    delivered_total_with_tip = delivered_total + tip
    conn.close()
    return jsonify({
        'active_count': active_count,
        'delivered_count': delivered_count,
        'canceled_count': canceled_count,
        'delivered_total': delivered_total,
        'delivered_tip_10': tip,
        'delivered_total_with_tip': delivered_total_with_tip
    })

@app.route('/api/tenants', methods=['GET'])
def tenants():
    items = []
    try:
        for name in os.listdir(CONFIG_DIR):
            if not name.endswith('.json'):
                continue
            p = os.path.join(CONFIG_DIR, name)
            try:
                import json
                with open(p, 'r', encoding='utf-8') as f:
                    j = json.load(f)
                meta = j.get('meta') or {}
                slug = meta.get('slug') or name.replace('.json','')
                branding = meta.get('branding') or {}
                items.append({'slug': slug, 'name': (branding.get('name') or slug)})
            except Exception:
                continue
    except Exception:
        pass
    items = sorted(items, key=lambda x: x['slug'])
    return jsonify({'tenants': items})

@app.route('/api/tenant_sla', methods=['GET'])
def tenant_sla():
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    warn = 15
    crit = 30
    try:
        import json
        p = os.path.join(CONFIG_DIR, f'{slug}.json')
        if os.path.isfile(p):
            with open(p, 'r', encoding='utf-8') as f:
                j = json.load(f)
            sla = j.get('sla') or {}
            w = int(sla.get('warning_minutes') or warn)
            c = int(sla.get('critical_minutes') or crit)
            warn = max(1, w)
            crit = max(warn + 1, c)
    except Exception:
        pass
    return jsonify({'warning_minutes': warn, 'critical_minutes': crit})

@app.route('/api/tenant_prefs', methods=['GET'])
def tenant_prefs():
    slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    tip_percent = 10
    tip_default_enabled = True
    ticket_format = 'full'
    try:
        import json
        p = os.path.join(CONFIG_DIR, f'{slug}.json')
        if os.path.isfile(p):
            with open(p, 'r', encoding='utf-8') as f:
                j = json.load(f)
            prefs = j.get('prefs') or {}
            tperc = int(prefs.get('tip_percent') or tip_percent)
            tip_percent = max(0, min(100, tperc))
            ten = prefs.get('tip_default_enabled')
            if isinstance(ten, bool):
                tip_default_enabled = ten
            tfmt = str(prefs.get('ticket_format') or ticket_format)
            if tfmt in ('compact','full'):
                ticket_format = tfmt
    except Exception:
        pass
    return jsonify({
        'tip_percent': tip_percent,
        'tip_default_enabled': tip_default_enabled,
        'ticket_format': ticket_format
    })

@app.route('/api/archive/bulk', methods=['POST'])
def archive_bulk():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    a_type = str(payload.get('type') or '')
    tenant_slug = str(payload.get('tenant_slug') or '')
    hours = int(payload.get('hours') or 24)
    if a_type not in ('delivered','canceled'):
        return jsonify({'error': 'type inválido'}), 400
    cutoff_dt = datetime.utcnow() - timedelta(hours=max(1, hours))
    cutoff = cutoff_dt.isoformat()
    conn = get_db()
    cur = conn.cursor()
    base_status = 'entregado' if a_type == 'delivered' else 'cancelado'
    sql = """
        SELECT o.id, o.tenant_slug
        FROM orders o
        JOIN (
          SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = ? GROUP BY order_id
        ) h ON h.order_id = o.id
        LEFT JOIN archived_orders a ON a.order_id = o.id AND a.type = ?
        WHERE a.order_id IS NULL AND h.last_change <= ?
    """
    params = [base_status, a_type, cutoff]
    if tenant_slug:
        sql += " AND o.tenant_slug = ?"
        params.append(tenant_slug)
    cur.execute(sql, params)
    rows = cur.fetchall()
    count = 0
    for r in rows:
        oid = r[0]
        slug = r[1]
        cur.execute(
            "INSERT OR IGNORE INTO archived_orders (order_id, tenant_slug, type, archived_at) VALUES (?, ?, ?, ?)",
            (oid, slug, a_type, datetime.utcnow().isoformat())
        )
        count += (cur.rowcount or 0)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'archived_count': count, 'type': a_type, 'tenant_slug': tenant_slug or None, 'hours': hours})

@app.route('/api/auth/login', methods=['POST'])
def auth_login():
    payload = request.get_json(silent=True) or {}
    u = str(payload.get('username') or '')
    p = str(payload.get('password') or '')
    env_user = os.environ.get('ADMIN_USERNAME') or ''
    env_hash = os.environ.get('ADMIN_PASSWORD_HASH') or ''
    env_pass = os.environ.get('ADMIN_PASSWORD') or ''
    ok = False
    if env_user and u == env_user:
        if env_hash:
            try:
                ok = check_password_hash(env_hash, p)
            except Exception:
                ok = False
        else:
            ok = bool(env_pass) and p == env_pass
    if not ok and not env_user:
        if u == 'prueba' and p == 'prueba123':
            ok = True
    if not ok:
        return jsonify({'error': 'credenciales inválidas'}), 401
    session['admin_auth'] = True
    session['admin_user'] = u
    session['csrf_token'] = secrets.token_urlsafe(32)
    return jsonify({'ok': True})

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    return jsonify({'authenticated': is_authed(), 'user': session.get('admin_user') or ''})

@app.route('/api/auth/csrf', methods=['GET'])
def auth_csrf():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    return jsonify({'token': get_csrf_token()})

# Health-check simple
@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat()})

# Colocar el catch-all estático AL FINAL para no interceptar rutas /api/*
@app.route('/<path:path>')
def static_proxy(path):
    # Evitar capturar prefijos de API
    if path.startswith('api/'):
        # Dejar que las rutas de API manejen estas solicitudes
        return jsonify({'error': 'Ruta de API no válida'}), 404
    # Servir cualquier archivo estático del proyecto
    return send_from_directory(BASE_DIR, path)

# Evitar caché para respuestas dinámicas
@app.after_request
def add_cache_headers(resp):
    try:
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
    except Exception:
        pass
    return resp

if __name__ == '__main__':
    init_db()
    start_background_tasks()
    print(f"Servidor Flask ejecutándose en http://localhost:{PORT}/ (raíz: {BASE_DIR})")
    # Escuchar en IPv4 para máxima compatibilidad en Windows
    app.run(host='0.0.0.0', port=PORT)