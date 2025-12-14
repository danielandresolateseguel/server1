import os
import tempfile
import sqlite3
import argparse
from datetime import datetime, timedelta
from flask import Flask, request, jsonify, send_from_directory, session
import secrets
import unicodedata
from werkzeug.security import check_password_hash, generate_password_hash
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

# Credenciales por defecto para el entorno de desarrollo
if not os.environ.get('ADMIN_USERNAME'):
    os.environ['ADMIN_USERNAME'] = 'admin'
if not os.environ.get('ADMIN_PASSWORD_HASH') and not os.environ.get('ADMIN_PASSWORD'):
    os.environ['ADMIN_PASSWORD'] = 'admin123'
if not os.environ.get('ALLOW_ALL_LOGIN'):
    os.environ['ALLOW_ALL_LOGIN'] = '1'

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
        cur.execute("PRAGMA table_info(orders)")
        cols = [r[1] for r in cur.fetchall()]  # r[1] = name
        if 'order_notes' not in cols:
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
    # Inventario de productos
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug TEXT NOT NULL,
            product_id TEXT NOT NULL,
            name TEXT NOT NULL,
            price INTEGER NOT NULL,
            stock INTEGER NOT NULL DEFAULT 0,
            active INTEGER NOT NULL DEFAULT 1,
            UNIQUE(tenant_slug, product_id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_products_tenant ON products(tenant_slug)")
    # Ampliar esquema de productos para detalles y variantes (si no existen)
    try:
        cur.execute("PRAGMA table_info(products)")
        cols_prod = [r[1] for r in cur.fetchall()]
        if 'details' not in cols_prod:
            cur.execute("ALTER TABLE products ADD COLUMN details TEXT")
        if 'variants_json' not in cols_prod:
            cur.execute("ALTER TABLE products ADD COLUMN variants_json TEXT")
        conn.commit()
    except Exception:
        pass
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS admin_users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug TEXT NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            UNIQUE(tenant_slug, username)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_admin_users_tenant ON admin_users(tenant_slug)")
    # Auditoría de eventos
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS order_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            event_type TEXT NOT NULL,
            actor TEXT,
            terminal TEXT,
            amount_delta INTEGER,
            payload_json TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES orders(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_order_events_order ON order_events(order_id)")
    # Sesiones de caja
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cash_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tenant_slug TEXT NOT NULL,
            opened_at TEXT NOT NULL,
            opened_by TEXT,
            opening_amount INTEGER NOT NULL,
            notes_open TEXT,
            closed_at TEXT,
            closed_by TEXT,
            closing_amount INTEGER,
            notes_close TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cash_sessions_tenant ON cash_sessions(tenant_slug)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cash_sessions_open ON cash_sessions(tenant_slug, opened_at)")
    # Movimientos de caja
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cash_movements (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            amount INTEGER NOT NULL,
            note TEXT,
            actor TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(session_id) REFERENCES cash_sessions(id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cash_movements_session ON cash_movements(session_id)")
    try:
        cur.execute("PRAGMA table_info(cash_sessions)")
        cols_cash = [r[1] for r in cur.fetchall()]
        if 'closing_diff' not in cols_cash:
            cur.execute("ALTER TABLE cash_sessions ADD COLUMN closing_diff INTEGER")
            conn.commit()
    except Exception:
        pass
    conn.commit()
    conn.close()

def seed_products_from_config():
    try:
        import json
        conn = get_db()
        cur = conn.cursor()
        for name in os.listdir(CONFIG_DIR):
            if not name.endswith('.json'):
                continue
            p = os.path.join(CONFIG_DIR, name)
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    j = json.load(f)
                meta = j.get('meta') or {}
                slug = meta.get('slug') or name.replace('.json','')
                catalog = j.get('catalog') or []
                for it in catalog:
                    pid = str(it.get('id') or '').strip()
                    nm = str(it.get('name') or '').strip()
                    price = int(it.get('price') or 0)
                    if not pid or not nm:
                        continue
                    cur.execute(
                        "INSERT OR IGNORE INTO products (tenant_slug, product_id, name, price, stock, active) VALUES (?, ?, ?, ?, ?, 1)",
                        (slug, pid, nm, price, 50)
                    )
            except Exception:
                continue
        conn.commit()
        conn.close()
    except Exception:
        pass

def backfill_product_details_from_config():
    try:
        import json
        conn = get_db()
        cur = conn.cursor()
        for name in os.listdir(CONFIG_DIR):
            if not name.endswith('.json'):
                continue
            p = os.path.join(CONFIG_DIR, name)
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    j = json.load(f)
                meta = j.get('meta') or {}
                slug = meta.get('slug') or name.replace('.json','')
                catalog = j.get('catalog') or []
                for it in catalog:
                    pid = str(it.get('id') or '').strip()
                    desc = str(it.get('description') or '').strip()
                    if not pid or not desc:
                        continue
                    cur.execute(
                        "UPDATE products SET details = ? WHERE tenant_slug = ? AND product_id = ? AND (details IS NULL OR TRIM(details) = '')",
                        (desc, slug, pid)
                    )
            except Exception:
                continue
        conn.commit()
        conn.close()
    except Exception:
        pass

def seed_admin_users_from_env():
    try:
        admin_user = os.environ.get('ADMIN_USERNAME') or 'admin'
        admin_pass = os.environ.get('ADMIN_PASSWORD') or 'admin123'
        admin_legacy_pass = os.environ.get('ADMIN_LEGACY_PASSWORD') or 'GastroPanel!123'
        import json
        conn = get_db()
        cur = conn.cursor()
        for name in os.listdir(CONFIG_DIR):
            if not name.endswith('.json'):
                continue
            p = os.path.join(CONFIG_DIR, name)
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    j = json.load(f)
                meta = j.get('meta') or {}
                slug = meta.get('slug') or name.replace('.json','')
                ph = generate_password_hash(admin_pass)
                cur.execute(
                    "INSERT OR IGNORE INTO admin_users (tenant_slug, username, password_hash) VALUES (?, ?, ?)",
                    (slug, admin_user, ph)
                )
                # Inserta también admin con contraseña legacy si corresponde
                if admin_legacy_pass:
                    ph_legacy = generate_password_hash(admin_legacy_pass)
                    cur.execute(
                        "INSERT OR IGNORE INTO admin_users (tenant_slug, username, password_hash) VALUES (?, ?, ?)",
                        (slug, 'admin', ph_legacy)
                    )
                admins = j.get('admins') or meta.get('admins') or []
                for adm in admins:
                    try:
                        un = str(adm.get('username') or '').strip()
                        pw = str(adm.get('password') or '')
                        if not un or not pw:
                            continue
                        ph2 = generate_password_hash(pw)
                        cur.execute(
                            "INSERT OR IGNORE INTO admin_users (tenant_slug, username, password_hash) VALUES (?, ?, ?)",
                            (slug, un, ph2)
                        )
                    except Exception:
                        continue
            except Exception:
                continue
        conn.commit()
        conn.close()
    except Exception:
        pass

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
    # Validar stock y registrar ítems
    for it in items:
        qty = int(it.get('quantity', it.get('qty', 1)) or 1)
        pid = it.get('id')
        # Validar existencia y stock
        cur.execute("SELECT stock FROM products WHERE tenant_slug = ? AND product_id = ?", (tenant_slug, pid))
        row = cur.fetchone()
        if not row:
            try:
                nm = str(it.get('name') or '').strip() or 'Producto'
                pr = int(it.get('price') or 0)
                cur.execute(
                    "INSERT OR IGNORE INTO products (tenant_slug, product_id, name, price, stock, active) VALUES (?, ?, ?, ?, ?, 1)",
                    (tenant_slug, pid, nm, max(0, pr), 50)
                )
                conn.commit()
                cur.execute("SELECT stock FROM products WHERE tenant_slug = ? AND product_id = ?", (tenant_slug, pid))
                row = cur.fetchone()
            except Exception:
                conn.rollback()
                conn.close()
                return jsonify({'error': 'producto no encontrado', 'product_id': pid}), 400
        stock = int((row[0] if row else 0) or 0)
        if stock < qty:
            conn.rollback()
            conn.close()
            return jsonify({'error': 'stock insuficiente', 'product_id': pid, 'stock': stock, 'requested': qty}), 400
        # Registrar ítem
        cur.execute(
            """
            INSERT INTO order_items (order_id, tenant_slug, product_id, name, qty, unit_price, modifiers_json, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                order_id,
                tenant_slug,
                pid,
                it.get('name'),
                qty,
                int(it.get('price', 0) or 0),
                str(it.get('modifiers') or {}),
                it.get('notes') or ''
            )
        )
        # Decrementar stock
        cur.execute("UPDATE products SET stock = stock - ? WHERE tenant_slug = ? AND product_id = ?", (qty, tenant_slug, pid))
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
    # Total con mismos filtros (status, búsqueda y rango)
    count_sql = "SELECT COUNT(*) as c FROM orders WHERE tenant_slug = ?"
    count_params = [tenant_slug]
    if status:
        count_sql += " AND status = ?"
        count_params.append(status)
    if q:
        try:
            qid = int(q)
            count_sql += " AND id = ?"
            count_params.append(qid)
        except Exception:
            like = f"%{q}%"
            count_sql += " AND (COALESCE(address_json,'') LIKE ? OR COALESCE(customer_name,'') LIKE ? OR COALESCE(customer_phone,'') LIKE ? OR COALESCE(table_number,'') LIKE ?)"
            count_params.extend([like, like, like, like])
    if from_date:
        count_sql += " AND created_at >= ?"
        count_params.append(from_date)
    if to_date:
        count_sql += " AND created_at <= ?"
        count_params.append(to_date)
    cur.execute(count_sql, count_params)
    total_count = cur.fetchone()[0]
    conn.close()
    return jsonify({'orders': data, 'count': len(data), 'total': total_count, 'limit': limit, 'offset': offset})

@app.route('/api/cash/movements', methods=['GET'])
def cash_movements_list():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    session_id = request.args.get('session_id')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    try:
        sid = int(session_id or 0)
    except Exception:
        sid = 0
    conn = get_db()
    cur = conn.cursor()
    movements = []
    if sid > 0:
        cur.execute("SELECT id, session_id, type, amount, note, actor, created_at FROM cash_movements WHERE session_id = ? ORDER BY id ASC", (sid,))
        rows = cur.fetchall()
        movements = [dict(r) for r in rows]
    elif from_date or to_date:
        q = (
            "SELECT m.id, m.session_id, m.type, m.amount, m.note, m.actor, m.created_at "
            "FROM cash_movements m JOIN cash_sessions s ON m.session_id = s.id "
            "WHERE s.tenant_slug = ?"
        )
        params = [tenant_slug]
        if from_date:
            q += " AND m.created_at >= ?"
            params.append(from_date)
        if to_date:
            q += " AND m.created_at <= ?"
            params.append(to_date)
        q += " ORDER BY m.id ASC"
        cur.execute(q, params)
        rows = cur.fetchall()
        movements = [dict(r) for r in rows]
    conn.close()
    return jsonify({'tenant_slug': tenant_slug, 'session_id': sid, 'movements': movements})

@app.route('/api/orders/<int:order_id>/status', methods=['PATCH'])
def update_order_status(order_id):
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    new_status = payload.get('status')
    reason = (payload.get('reason') or '').strip()
    if new_status not in ('pendiente', 'preparacion', 'listo', 'en_camino', 'entregado', 'cancelado'):
        return jsonify({'error': 'status inválido'}), 400
    conn = get_db()
    cur = conn.cursor()
    if new_status == 'entregado':
        cur.execute("SELECT tenant_slug FROM orders WHERE id = ?", (order_id,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'orden no encontrada'}), 404
        tenant_slug = str(row[0] or '')
        cur.execute("SELECT id FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
        sess = cur.fetchone()
        if not sess:
            conn.close()
            return jsonify({'error': 'no hay sesión de caja abierta'}), 400
    cur.execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))
    conn.commit()
    # Registrar historial
    cur.execute("INSERT INTO order_status_history (order_id, status, changed_at) VALUES (?, ?, ?)", (order_id, new_status, datetime.utcnow().isoformat()))
    conn.commit()
    try:
        actor = session.get('admin_user') or ''
        meta = {}
        if reason and new_status == 'cancelado':
            meta['reason'] = reason
        cur.execute(
            "INSERT INTO order_events (order_id, event_type, actor, amount_delta, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (order_id, ('canceled' if new_status == 'cancelado' else 'status_change'), actor, 0, __import__('json').dumps(meta), datetime.utcnow().isoformat())
        )
        conn.commit()
    except Exception:
        pass
    conn.close()
    return jsonify({'order_id': order_id, 'status': new_status})

@app.route('/api/orders/<int:order_id>/events', methods=['POST'])
def create_order_event(order_id):
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    ev_type = (payload.get('type') or '').strip().lower()
    if not ev_type:
        return jsonify({'error': 'tipo de evento requerido'}), 400
    amount_delta = int(payload.get('amount_delta') or 0)
    meta = payload.get('meta') or {}
    actor = session.get('admin_user') or ''
    term = (payload.get('terminal') or '')
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO order_events (order_id, event_type, actor, terminal, amount_delta, payload_json, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (order_id, ev_type, actor, term, amount_delta, __import__('json').dumps(meta), datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()
    return jsonify({'order_id': order_id, 'type': ev_type})

@app.route('/api/orders/<int:order_id>/events', methods=['GET'])
def list_order_events(order_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, event_type, actor, terminal, amount_delta, payload_json, created_at FROM order_events WHERE order_id = ? ORDER BY id ASC", (order_id,))
    rows = cur.fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    return jsonify({'events': items})

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
    # Eventos
    cur.execute(
        "SELECT event_type, actor, terminal, amount_delta, payload_json, created_at FROM order_events WHERE order_id = ? ORDER BY id ASC",
        (order_id,)
    )
    ev_rows = cur.fetchall()
    conn.close()
    order = dict(order_row)
    items = [dict(r) for r in item_rows]
    history = [dict(r) for r in hist_rows]
    events = [dict(r) for r in ev_rows]
    return jsonify({'order': order, 'items': items, 'history': history, 'events': events})

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
    try:
        tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
        from_date = request.args.get('from')
        to_date = request.args.get('to')
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
        cur.execute("SELECT COUNT(*) FROM orders WHERE tenant_slug = ? AND status NOT IN ('entregado','cancelado')", (tenant_slug,))
        active_count = cur.fetchone()[0]
        base_join_del = (
            "SELECT COUNT(*) FROM orders o "
            "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
            "WHERE o.tenant_slug = ? AND o.status = 'entregado'"
        )
        base_join_can = (
            "SELECT COUNT(*) FROM orders o "
            "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'cancelado' GROUP BY order_id) h ON h.order_id = o.id "
            "WHERE o.tenant_slug = ? AND o.status = 'cancelado'"
        )
        params_del = [tenant_slug]
        params_can = [tenant_slug]
        if from_date:
            base_join_del += " AND h.last_change >= ?"
            base_join_can += " AND h.last_change >= ?"
            params_del.append(from_date)
            params_can.append(from_date)
        if to_date:
            base_join_del += " AND h.last_change <= ?"
            base_join_can += " AND h.last_change <= ?"
            params_del.append(to_date)
            params_can.append(to_date)
        cur.execute(base_join_del, params_del)
        delivered_count = cur.fetchone()[0]
        cur.execute(base_join_can, params_can)
        canceled_count = cur.fetchone()[0]
        cur.execute(
            base_join_del.replace("SELECT COUNT(*)", "SELECT COALESCE(SUM(o.total),0)"),
            params_del
        )
        delivered_total = int(cur.fetchone()[0] or 0)
        tip = (delivered_total + 5) // 10
        delivered_total_with_tip = delivered_total + tip
        avg_prep = 0
        avg_listo = 0
        avg_entregado = 0
        try:
            where_exists = "EXISTS(SELECT 1 FROM order_status_history h WHERE h.order_id = o.id AND h.status = 'entregado'"
            p2 = [tenant_slug]
            if from_date:
                where_exists += " AND h.changed_at >= ?"
                p2.append(from_date)
            if to_date:
                where_exists += " AND h.changed_at <= ?"
                p2.append(to_date)
            where_exists += ")"
            cur.execute(
                f"""
                SELECT o.id, o.created_at,
                       (SELECT h.changed_at FROM order_status_history h WHERE h.order_id = o.id AND h.status = 'preparacion' ORDER BY h.id ASC LIMIT 1) AS prep_at,
                       (SELECT h.changed_at FROM order_status_history h WHERE h.order_id = o.id AND h.status = 'listo' ORDER BY h.id ASC LIMIT 1) AS listo_at,
                       (SELECT h.changed_at FROM order_status_history h WHERE h.order_id = o.id AND h.status = 'entregado' ORDER BY h.id ASC LIMIT 1) AS entregado_at
                FROM orders o
                WHERE o.tenant_slug = ? AND {where_exists}
                """,
                p2
            )
            rows = cur.fetchall()
            def _p(s):
                import datetime
                try:
                    return datetime.datetime.fromisoformat(str(s))
                except Exception:
                    return None
            ps = []
            ls = []
            es = []
            for r in rows:
                created = _p(r[1])
                prep_at = _p(r[2])
                listo_at = _p(r[3])
                entregado_at = _p(r[4])
                if created and prep_at:
                    ps.append(max(0, int((prep_at - created).total_seconds() // 60)))
                if created and listo_at:
                    ls.append(max(0, int((listo_at - created).total_seconds() // 60)))
                if created and entregado_at:
                    es.append(max(0, int((entregado_at - created).total_seconds() // 60)))
            def _avg(a):
                try:
                    return int(sum(a) // max(1, len(a)))
                except Exception:
                    return 0
            avg_prep = _avg(ps)
            avg_listo = _avg(ls)
            avg_entregado = _avg(es)
        except Exception:
            pass
        conn.close()
        return jsonify({
            'active_count': active_count,
            'delivered_count': delivered_count,
            'canceled_count': canceled_count,
            'delivered_total': delivered_total,
            'delivered_tip_10': tip,
            'delivered_total_with_tip': delivered_total_with_tip,
            'avg_to_preparacion_min': avg_prep,
            'avg_to_listo_min': avg_listo,
            'avg_to_entregado_min': avg_entregado
        })
    except Exception:
        try:
            return jsonify({
                'active_count': 0,
                'delivered_count': 0,
                'canceled_count': 0,
                'delivered_total': 0,
                'delivered_tip_10': 0,
                'delivered_total_with_tip': 0,
                'avg_to_preparacion_min': 0,
                'avg_to_listo_min': 0,
                'avg_to_entregado_min': 0
            })
        except Exception:
            return jsonify({'error': 'metrics unavailable'}), 500

@app.route('/api/metrics/aggregate', methods=['GET'])
def metrics_aggregate():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    group = (request.args.get('group') or 'day').strip().lower()
    date_field = (request.args.get('date_field') or 'delivered').strip().lower()
    if date_field not in ('delivered','order'):
        date_field = 'delivered'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10:
                return s + ('T23:59:59' if end else 'T00:00:00')
        except Exception:
            pass
        return s
    from_date = _norm_date(from_date, end=False)
    to_date = _norm_date(to_date, end=True)
    # Base column for buckets and filters
    base_col = "h.last_change" if date_field == 'delivered' else "o.created_at"
    # Bucket expression
    bucket_expr = f"strftime('%Y-%m-%d', REPLACE({base_col},'T',' '))"
    if group == 'month':
        bucket_expr = f"strftime('%Y-%m', REPLACE({base_col},'T',' '))"
    elif group == 'year':
        bucket_expr = f"strftime('%Y', REPLACE({base_col},'T',' '))"
    elif group == 'week':
        bucket_expr = f"strftime('%Y', REPLACE({base_col},'T',' ')) || '-W' || strftime('%W', REPLACE({base_col},'T',' '))"
    conn = get_db()
    cur = conn.cursor()
    base_del = (
        f"SELECT {bucket_expr} AS bucket, COUNT(*) AS delivered_count, COALESCE(SUM(o.total),0) AS delivered_total "
        "FROM orders o "
        + ("JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id " if date_field == 'delivered' else "") +
        "WHERE o.tenant_slug = ? AND o.status = 'entregado'"
    )
    params_del = [tenant_slug]
    if from_date:
        base_del += f" AND {base_col} >= ?"
        params_del.append(from_date)
    if to_date:
        base_del += f" AND {base_col} <= ?"
        params_del.append(to_date)
    base_del += " GROUP BY bucket ORDER BY bucket ASC"
    cur.execute(base_del, params_del)
    rows_del = cur.fetchall()
    # Canceled
    base_can = (
        f"SELECT {bucket_expr} AS bucket, COUNT(*) AS canceled_count "
        "FROM orders o "
        + ("JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'cancelado' GROUP BY order_id) h ON h.order_id = o.id " if date_field == 'delivered' else "") +
        "WHERE o.tenant_slug = ? AND o.status = 'cancelado'"
    )
    params_can = [tenant_slug]
    if from_date:
        base_can += f" AND {base_col} >= ?"
        params_can.append(from_date)
    if to_date:
        base_can += f" AND {base_col} <= ?"
        params_can.append(to_date)
    base_can += " GROUP BY bucket ORDER BY bucket ASC"
    cur.execute(base_can, params_can)
    rows_can = cur.fetchall()
    conn.close()
    agg = {}
    for r in rows_del:
        b = r[0]
        agg[b] = {
            'period': b,
            'delivered_count': int(r[1] or 0),
            'delivered_total': int(r[2] or 0)
        }
    for r in rows_can:
        b = r[0]
        if b not in agg:
            agg[b] = {
                'period': b,
                'delivered_count': 0,
                'delivered_total': 0
            }
        agg[b]['canceled_count'] = int(r[1] or 0)
    # Ensure canceled_count exists
    for k in list(agg.keys()):
        if 'canceled_count' not in agg[k]:
            agg[k]['canceled_count'] = 0
        # add tip and total_with_tip
        tip = (agg[k]['delivered_total'] + 5) // 10
        agg[k]['delivered_tip_10'] = tip
        agg[k]['delivered_total_with_tip'] = agg[k]['delivered_total'] + tip
    buckets = sorted(agg.keys())
    return jsonify({'group': group, 'date_field': date_field, 'tenant_slug': tenant_slug, 'from': from_date, 'to': to_date, 'rows': [agg[b] for b in buckets]})

@app.route('/api/metrics/aggregate.csv', methods=['GET'])
def metrics_aggregate_csv():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    group = (request.args.get('group') or 'day').strip().lower()
    date_field = (request.args.get('date_field') or 'delivered').strip().lower()
    if date_field not in ('delivered','order'):
        date_field = 'delivered'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10:
                return s + ('T23:59:59' if end else 'T00:00:00')
        except Exception:
            pass
        return s
    from_date = _norm_date(from_date, end=False)
    to_date = _norm_date(to_date, end=True)
    base_col = "h.last_change" if date_field == 'delivered' else "o.created_at"
    bucket_expr = f"strftime('%Y-%m-%d', REPLACE({base_col},'T',' '))"
    if group == 'month':
        bucket_expr = f"strftime('%Y-%m', REPLACE({base_col},'T',' '))"
    elif group == 'year':
        bucket_expr = f"strftime('%Y', REPLACE({base_col},'T',' '))"
    elif group == 'week':
        bucket_expr = f"strftime('%Y', REPLACE({base_col},'T',' ')) || '-W' || strftime('%W', REPLACE({base_col},'T',' '))"
    conn = get_db()
    cur = conn.cursor()
    base_del = (
        f"SELECT {bucket_expr} AS bucket, COUNT(*) AS delivered_count, COALESCE(SUM(o.total),0) AS delivered_total "
        "FROM orders o "
        + ("JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id " if date_field == 'delivered' else "") +
        "WHERE o.tenant_slug = ? AND o.status = 'entregado'"
    )
    params_del = [tenant_slug]
    if from_date:
        base_del += f" AND {base_col} >= ?"
        params_del.append(from_date)
    if to_date:
        base_del += f" AND {base_col} <= ?"
        params_del.append(to_date)
    base_del += " GROUP BY bucket ORDER BY bucket ASC"
    cur.execute(base_del, params_del)
    rows_del = cur.fetchall()
    base_can = (
        f"SELECT {bucket_expr} AS bucket, COUNT(*) AS canceled_count "
        "FROM orders o "
        + ("JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'cancelado' GROUP BY order_id) h ON h.order_id = o.id " if date_field == 'delivered' else "") +
        "WHERE o.tenant_slug = ? AND o.status = 'cancelado'"
    )
    params_can = [tenant_slug]
    if from_date:
        base_can += f" AND {base_col} >= ?"
        params_can.append(from_date)
    if to_date:
        base_can += f" AND {base_col} <= ?"
        params_can.append(to_date)
    base_can += " GROUP BY bucket ORDER BY bucket ASC"
    cur.execute(base_can, params_can)
    rows_can = cur.fetchall()
    conn.close()
    agg = {}
    for r in rows_del:
        b = r[0]
        agg[b] = {
            'period': b,
            'delivered_count': int(r[1] or 0),
            'delivered_total': int(r[2] or 0)
        }
    for r in rows_can:
        b = r[0]
        if b not in agg:
            agg[b] = {
                'period': b,
                'delivered_count': 0,
                'delivered_total': 0
            }
        agg[b]['canceled_count'] = int(r[1] or 0)
    for k in list(agg.keys()):
        if 'canceled_count' not in agg[k]:
            agg[k]['canceled_count'] = 0
        tip = (agg[k]['delivered_total'] + 5) // 10
        agg[k]['delivered_tip_10'] = tip
        agg[k]['delivered_total_with_tip'] = agg[k]['delivered_total'] + tip
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['tenant_slug', tenant_slug])
    writer.writerow(['group', group])
    writer.writerow(['date_field', date_field])
    writer.writerow(['from', from_date or ''])
    writer.writerow(['to', to_date or ''])
    writer.writerow([])
    writer.writerow(['period','delivered_count','delivered_total','canceled_count','delivered_tip_10','delivered_total_with_tip'])
    for b in sorted(agg.keys()):
        r = agg[b]
        writer.writerow([r['period'], r['delivered_count'], r['delivered_total'], r['canceled_count'], r['delivered_tip_10'], r['delivered_total_with_tip']])
    from flask import Response
    resp = Response(output.getvalue(), mimetype='text/csv')
    fname = f"metrics_{tenant_slug}_{group}_{date_field}.csv"
    resp.headers['Content-Disposition'] = f"attachment; filename={fname}"
    return resp

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

@app.route('/api/tenant_sla', methods=['PATCH'])
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
    p = os.path.join(CONFIG_DIR, f'{slug}.json')
    if not os.path.isfile(p):
        return jsonify({'error': 'tenant no encontrado'}), 404
    try:
        import json
        with open(p, 'r', encoding='utf-8') as f:
            j = json.load(f)
        sla = j.get('sla') or {}
        sla['warning_minutes'] = w
        sla['critical_minutes'] = c
        j['sla'] = sla
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(j, f, ensure_ascii=False, indent=2)
    except Exception:
        return jsonify({'error': 'no se pudo guardar configuración'}), 500
    return jsonify({'ok': True, 'tenant_slug': slug, 'warning_minutes': w, 'critical_minutes': c})

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
    username = str(payload.get('username') or '')
    password = str(payload.get('password') or '')
    tenant_slug = str(payload.get('tenant_slug') or '')
    if not username or not password or not tenant_slug:
        return jsonify({'error': 'credenciales incompletas'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT password_hash FROM admin_users WHERE tenant_slug = ? AND username = ?", (tenant_slug, username))
    row = cur.fetchone()
    conn.close()
    if not row or not check_password_hash(row[0], password):
        return jsonify({'error': 'usuario o contraseña inválidos'}), 401
    session['admin_auth'] = True
    session['admin_user'] = username
    session['tenant_slug'] = tenant_slug
    session['csrf_token'] = secrets.token_urlsafe(32)
    return jsonify({'ok': True, 'tenant_slug': tenant_slug})

@app.route('/api/auth/login_dev', methods=['POST'])
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

@app.route('/api/auth/logout', methods=['POST'])
def auth_logout():
    session.clear()
    return jsonify({'ok': True})

@app.route('/api/auth/me', methods=['GET'])
def auth_me():
    return jsonify({'authenticated': is_authed(), 'user': session.get('admin_user') or '', 'tenant_slug': session.get('tenant_slug') or ''})

@app.route('/api/admin_users', methods=['GET'])
def admin_users_list():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    tenant_slug = request.args.get('tenant_slug') or session.get('tenant_slug') or ''
    if session.get('tenant_slug') and tenant_slug and session.get('tenant_slug') != tenant_slug:
        return jsonify({'error': 'acceso denegado al tenant'}), 403
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT username FROM admin_users WHERE tenant_slug = ? ORDER BY username ASC", (tenant_slug,))
    rows = cur.fetchall()
    conn.close()
    return jsonify({'tenant_slug': tenant_slug, 'users': [r[0] for r in rows]})

@app.route('/api/admin_users', methods=['POST'])
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
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM admin_users WHERE tenant_slug = ? AND username = ?", (tenant_slug, username))
    exists = cur.fetchone()
    if exists:
        conn.close()
        return jsonify({'error': 'usuario ya existe'}), 409
    ph = generate_password_hash(password)
    cur.execute("INSERT INTO admin_users (tenant_slug, username, password_hash) VALUES (?, ?, ?)", (tenant_slug, username, ph))
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'username': username, 'tenant_slug': tenant_slug})

@app.route('/api/cash/session', methods=['GET'])
def cash_session_get():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, tenant_slug, opened_at, opened_by, opening_amount, notes_open, closed_at, closed_by, closing_amount, notes_close FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'active': False})
    sess = dict(row)
    opened_at = sess['opened_at']
    base_join_del = (
        "SELECT COALESCE(SUM(o.total),0) FROM orders o "
        "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
        "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ?"
    )
    params = [tenant_slug, opened_at]
    cur.execute(base_join_del, params)
    delivered_total = int(cur.fetchone()[0] or 0)
    cur.execute(base_join_del.replace("COALESCE(SUM(o.total),0)", "COUNT(*)"), params)
    delivered_count = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COALESCE(SUM(CASE WHEN type='entrada' THEN amount ELSE 0 END),0) AS entradas, COALESCE(SUM(CASE WHEN type='salida' THEN amount ELSE 0 END),0) AS salidas FROM cash_movements WHERE session_id = ?", (sess['id'],))
    mv = cur.fetchone() or (0,0)
    entradas = int(mv[0] or 0)
    salidas = int(mv[1] or 0)
    conn.close()
    theoretical_cash = int(sess['opening_amount']) + entradas - salidas + delivered_total
    return jsonify({'active': True, 'session': sess, 'summary': {'delivered_count': delivered_count, 'delivered_total': delivered_total, 'entradas': entradas, 'salidas': salidas, 'theoretical_cash': theoretical_cash}})

@app.route('/api/cash/open', methods=['POST'])
def cash_open():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    tenant_slug = (payload.get('tenant_slug') or request.args.get('tenant_slug') or 'gastronomia-local1')
    opening_amount = int(payload.get('opening_amount') or 0)
    notes_open = (payload.get('notes') or '').strip()
    actor = session.get('admin_user') or ''
    now = datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    exists = cur.fetchone()
    if exists:
        conn.close()
        return jsonify({'error': 'ya existe una sesión de caja abierta'}), 400
    cur.execute("INSERT INTO cash_sessions (tenant_slug, opened_at, opened_by, opening_amount, notes_open) VALUES (?, ?, ?, ?, ?)", (tenant_slug, now, actor, opening_amount, notes_open))
    conn.commit()
    sid = cur.lastrowid
    conn.close()
    return jsonify({'session_id': sid, 'tenant_slug': tenant_slug, 'opened_at': now, 'opening_amount': opening_amount})

@app.route('/api/cash/close', methods=['POST'])
def cash_close():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    tenant_slug = (payload.get('tenant_slug') or request.args.get('tenant_slug') or 'gastronomia-local1')
    closing_amount = int(payload.get('closing_amount') or 0)
    notes_close = (payload.get('notes') or '').strip()
    actor = session.get('admin_user') or ''
    now = datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, opened_at, opening_amount FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'no hay sesión de caja abierta'}), 400
    sid = int(row[0])
    opened_at = str(row[1])
    opening_amount = int(row[2] or 0)
    base_join_del = (
        "SELECT COALESCE(SUM(o.total),0) FROM orders o "
        "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
        "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ?"
    )
    cur.execute(base_join_del, (tenant_slug, opened_at, now))
    delivered_total = int(cur.fetchone()[0] or 0)
    cur.execute("SELECT COALESCE(SUM(CASE WHEN type='entrada' THEN amount ELSE 0 END),0) AS entradas, COALESCE(SUM(CASE WHEN type='salida' THEN amount ELSE 0 END),0) AS salidas FROM cash_movements WHERE session_id = ?", (sid,))
    mv = cur.fetchone() or (0,0)
    entradas = int(mv[0] or 0)
    salidas = int(mv[1] or 0)
    theoretical_cash = opening_amount + entradas - salidas + delivered_total
    closing_diff = closing_amount - theoretical_cash
    cur.execute("UPDATE cash_sessions SET closed_at = ?, closed_by = ?, closing_amount = ?, notes_close = ?, closing_diff = ? WHERE id = ?", (now, actor, closing_amount, notes_close, closing_diff, sid))
    conn.commit()
    conn.close()
    return jsonify({'session_id': sid, 'tenant_slug': tenant_slug, 'opened_at': opened_at, 'closed_at': now, 'closing_amount': closing_amount, 'summary': {'opening_amount': opening_amount, 'entradas': entradas, 'salidas': salidas, 'delivered_total': delivered_total, 'theoretical_cash': theoretical_cash, 'closing_diff': closing_diff}})

@app.route('/api/cash/movement', methods=['POST'])
def cash_movement():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    tenant_slug = (payload.get('tenant_slug') or request.args.get('tenant_slug') or 'gastronomia-local1')
    mtype = (payload.get('type') or '').strip().lower()
    amount = int(payload.get('amount') or 0)
    note = (payload.get('note') or '').strip()
    if mtype not in ('entrada','salida'):
        return jsonify({'error': 'tipo inválido'}), 400
    if amount <= 0:
        return jsonify({'error': 'monto inválido'}), 400
    actor = session.get('admin_user') or ''
    now = datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return jsonify({'error': 'no hay sesión de caja abierta'}), 400
    sid = int(row[0])
    cur.execute("INSERT INTO cash_movements (session_id, type, amount, note, actor, created_at) VALUES (?, ?, ?, ?, ?, ?)", (sid, mtype, amount, note, actor, now))
    conn.commit()
    conn.close()
    return jsonify({'session_id': sid, 'type': mtype, 'amount': amount, 'note': note, 'created_at': now})

@app.route('/api/cash/session/orders', methods=['GET'])
def cash_session_orders():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    session_id = request.args.get('session_id')
    to_date = request.args.get('to')
    try:
        sid = int(session_id or 0)
    except Exception:
        sid = 0
    conn = get_db()
    cur = conn.cursor()
    opened_at = None
    closed_at = None
    if sid > 0:
        cur.execute("SELECT opened_at, closed_at FROM cash_sessions WHERE id = ? AND tenant_slug = ?", (sid, tenant_slug))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({'orders': []})
        opened_at = str(row[0] or '')
        closed_at = str(row[1] or '')
    else:
        cur.execute("SELECT id, opened_at FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({'orders': []})
        sid = int(row[0])
        opened_at = str(row[1] or '')
    if not opened_at:
        conn.close()
        return jsonify({'orders': []})
    if to_date:
        end_at = to_date
    else:
        end_at = closed_at or datetime.utcnow().isoformat()
    base = (
        "SELECT o.id, o.created_at, o.total FROM orders o "
        "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
        "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ? "
        "ORDER BY o.id DESC"
    )
    cur.execute(base, (tenant_slug, opened_at, end_at))
    rows = cur.fetchall()
    conn.close()
    return jsonify({'orders': [ {'id': int(r[0]), 'created_at': r[1], 'total': int(r[2] or 0) } for r in rows ], 'session_id': sid, 'from': opened_at, 'to': end_at})

@app.route('/api/cash/sessions', methods=['GET'])
def cash_sessions_list():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    limit = int(request.args.get('limit') or 50)
    offset = int(request.args.get('offset') or 0)
    date_field = (request.args.get('date_field') or 'closed').strip().lower()
    if date_field not in ('closed', 'opened'):
        date_field = 'closed'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
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
    base = "SELECT id, tenant_slug, opened_at, opened_by, opening_amount, notes_open, closed_at, closed_by, closing_amount, notes_close, closing_diff FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NOT NULL"
    params = [tenant_slug]
    col = 'closed_at' if date_field == 'closed' else 'opened_at'
    if from_date:
        base += f" AND {col} >= ?"
        params.append(from_date)
    if to_date:
        base += f" AND {col} <= ?"
        params.append(to_date)
    base += " ORDER BY closed_at DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    cur.execute(base, params)
    rows = cur.fetchall()
    sessions = []
    for r in rows:
        s = dict(r)
        sid = int(s['id'])
        opened_at = s.get('opened_at')
        closed_at = s.get('closed_at')
        cur.execute(
            "SELECT COALESCE(SUM(o.total),0), COALESCE(COUNT(*),0) FROM orders o "
            "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
            "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ?",
            (tenant_slug, opened_at, closed_at)
        )
        trow = cur.fetchone() or (0,0)
        delivered_total = int(trow[0] or 0)
        delivered_count = int(trow[1] or 0)
        cur.execute("SELECT COALESCE(SUM(CASE WHEN type='entrada' THEN amount ELSE 0 END),0), COALESCE(SUM(CASE WHEN type='salida' THEN amount ELSE 0 END),0) FROM cash_movements WHERE session_id = ?", (sid,))
        mrow = cur.fetchone() or (0,0)
        entradas = int(mrow[0] or 0)
        salidas = int(mrow[1] or 0)
        theoretical_cash = int(s.get('opening_amount') or 0) + entradas - salidas + delivered_total
        s['summary'] = {
            'delivered_total': delivered_total,
            'delivered_count': delivered_count,
            'entradas': entradas,
            'salidas': salidas,
            'theoretical_cash': theoretical_cash,
            'closing_diff': int(s.get('closing_diff') or 0)
        }
        sessions.append(s)
    conn.close()
    return jsonify({'sessions': sessions, 'limit': limit, 'offset': offset, 'count': len(sessions)})

@app.route('/api/cash/sessions/export.csv', methods=['GET'])
def cash_sessions_export_csv():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    date_field = (request.args.get('date_field') or 'closed').strip().lower()
    if date_field not in ('closed', 'opened'):
        date_field = 'closed'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
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
    base = "SELECT id, tenant_slug, opened_at, opened_by, opening_amount, notes_open, closed_at, closed_by, closing_amount, notes_close, closing_diff FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NOT NULL"
    params = [tenant_slug]
    col = 'closed_at' if date_field == 'closed' else 'opened_at'
    if from_date:
        base += f" AND {col} >= ?"
        params.append(from_date)
    if to_date:
        base += f" AND {col} <= ?"
        params.append(to_date)
    base += " ORDER BY closed_at DESC"
    cur.execute(base, params)
    rows = cur.fetchall()
    import io, csv
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['tenant_slug', 'opened_at', 'opened_by', 'opening_amount', 'notes_open', 'closed_at', 'closed_by', 'closing_amount', 'notes_close', 'delivered_total', 'entradas', 'salidas', 'theoretical_cash', 'closing_diff'])
    for r in rows:
        s = dict(r)
        sid = int(s['id'])
        opened_at = s.get('opened_at')
        closed_at = s.get('closed_at')
        cur.execute(
            "SELECT COALESCE(SUM(o.total),0) FROM orders o "
            "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
            "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ?",
            (tenant_slug, opened_at, closed_at)
        )
        delivered_total = int((cur.fetchone() or (0,))[0] or 0)
        cur.execute("SELECT COALESCE(SUM(CASE WHEN type='entrada' THEN amount ELSE 0 END),0), COALESCE(SUM(CASE WHEN type='salida' THEN amount ELSE 0 END),0) FROM cash_movements WHERE session_id = ?", (sid,))
        mrow = cur.fetchone() or (0,0)
        entradas = int(mrow[0] or 0)
        salidas = int(mrow[1] or 0)
        theoretical_cash = int(s.get('opening_amount') or 0) + entradas - salidas + delivered_total
        writer.writerow([
            s.get('tenant_slug'), s.get('opened_at'), s.get('opened_by'), int(s.get('opening_amount') or 0), s.get('notes_open'), s.get('closed_at'), s.get('closed_by'), int(s.get('closing_amount') or 0), s.get('notes_close'), delivered_total, entradas, salidas, theoretical_cash, int(s.get('closing_diff') or 0)
        ])
    conn.close()
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = 'attachment; filename="cash_sessions.csv"'
    return resp
@app.route('/api/products', methods=['GET'])
def list_products():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        "SELECT product_id, name, price, stock, active, COALESCE(details,'') as details, COALESCE(variants_json,'') as variants_json FROM products WHERE tenant_slug = ? ORDER BY name ASC",
        (tenant_slug,)
    )
    rows = cur.fetchall()
    conn.close()
    items = [{'id': r[0], 'name': r[1], 'price': int(r[2] or 0), 'stock': int(r[3] or 0), 'active': bool(r[4]), 'details': r[5] or '', 'variants': r[6] or ''} for r in rows]
    return jsonify({'products': items, 'tenant_slug': tenant_slug})

@app.route('/api/products/<product_id>', methods=['PATCH'])
def update_product(product_id):
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    if session.get('tenant_slug') and session.get('tenant_slug') != tenant_slug:
        return jsonify({'error': 'acceso denegado al tenant'}), 403
    payload = request.get_json(silent=True) or {}
    fields = []
    params = []
    if 'stock' in payload:
        try:
            s = int(payload.get('stock'))
            fields.append('stock = ?')
            params.append(max(0, s))
        except Exception:
            return jsonify({'error': 'stock inválido'}), 400
    if 'price' in payload:
        try:
            pr = int(payload.get('price'))
            fields.append('price = ?')
            params.append(max(0, pr))
        except Exception:
            return jsonify({'error': 'price inválido'}), 400
    if 'active' in payload:
        try:
            ac = 1 if bool(payload.get('active')) else 0
            fields.append('active = ?')
            params.append(ac)
        except Exception:
            return jsonify({'error': 'active inválido'}), 400
    if 'name' in payload:
        nm = str(payload.get('name') or '').strip()
        if not nm:
            return jsonify({'error': 'name requerido'}), 400
        fields.append('name = ?')
        params.append(nm)
    if 'details' in payload:
        dt = str(payload.get('details') or '').strip()
        fields.append('details = ?')
        params.append(dt)
    if 'variants' in payload:
        try:
            import json as _json
            v = payload.get('variants')
            if isinstance(v, str):
                # permitir pasar JSON como string
                _json.loads(v)
                fields.append('variants_json = ?')
                params.append(v)
            else:
                fields.append('variants_json = ?')
                params.append(_json.dumps(v or []))
        except Exception:
            return jsonify({'error': 'variants inválido'}), 400
    if not fields:
        return jsonify({'error': 'sin cambios'}), 400
    params.extend([tenant_slug, product_id])
    conn = get_db()
    cur = conn.cursor()
    cur.execute(f"UPDATE products SET {', '.join(fields)} WHERE tenant_slug = ? AND product_id = ?", params)
    conn.commit()
    conn.close()
    return jsonify({'ok': True, 'product_id': product_id})

@app.route('/api/auth/csrf', methods=['GET'])
def auth_csrf():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    return jsonify({'token': get_csrf_token()})

# Health-check simple
@app.route('/api/ping', methods=['GET'])
def ping():
    return jsonify({'status': 'ok', 'time': datetime.utcnow().isoformat()})

@app.route('/api/print/ticket/<int:order_id>', methods=['POST'])
def print_ticket(order_id):
    try:
        if not is_authed():
            return jsonify({'error': 'no autorizado'}), 401
        if not check_csrf():
            return jsonify({'error': 'csrf inválido'}), 403
        if os.name != 'nt':
            return jsonify({'error': 'solo disponible en Windows'}), 501
        conn = get_db()
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, tenant_slug, customer_name, customer_phone, order_type, table_number, address_json, status, total, payment_method, payment_status, created_at, order_notes
            FROM orders WHERE id = ?
            """,
            (order_id,)
        )
        row = cur.fetchone()
        if not row:
            conn.close()
            return jsonify({'error': 'orden no encontrada'}), 404
        cur.execute(
            """
            SELECT name, qty, unit_price, notes
            FROM order_items WHERE order_id = ? ORDER BY id ASC
            """,
            (order_id,)
        )
        items = cur.fetchall()
        conn.close()
        o = dict(row)
        # Construcción del ticket en texto plano (monoespaciado)
        def up(s):
            try:
                return unicodedata.normalize('NFKD', str(s or '')).encode('ascii', 'ignore').decode('ascii').upper()
            except Exception:
                return str(s or '').upper()
        lines = []
        lines.append(f"PEDIDO #{o['id']}")
        if (o.get('order_type') or '').lower() == 'mesa':
            lines.append(f"MESA {o.get('table_number') or ''}")
        else:
            dest = (o.get('address_json') or '').strip()
            if dest:
                lines.append(f"DESTINO: {dest}")
        dt = o.get('created_at') or ''
        if dt:
            lines.append(f"FECHA: {dt}")
        phone = o.get('customer_phone') or ''
        if phone:
            lines.append(f"TEL: {phone}")
        lines.append("")
        for r in items:
            qty = int(r['qty'] or 0)
            name = up(r['name'])
            lines.append(f"{qty:>2}  {name}")
            n = (r['notes'] or '').strip()
            if n:
                lines.append(f"    - {up(n)}")
        onotes = (o.get('order_notes') or '').strip()
        if onotes:
            lines.append("")
            lines.append(f"NOTAS: {up(onotes)}")
        lines.append("")
        total = int(o.get('total') or 0)
        lines.append(f"TOTAL: ${total}")
        content = "\r\n".join(lines) + "\r\n"
        fd, path = tempfile.mkstemp(prefix='ticket_', suffix='.txt')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception:
            try:
                os.close(fd)
            except Exception:
                pass
            return jsonify({'error': 'no se pudo crear archivo temporal'}), 500
        try:
            os.startfile(path, 'print')
        except Exception as e:
            try:
                os.remove(path)
            except Exception:
                pass
            return jsonify({'error': f'no se pudo imprimir: {e}'}), 500
        return jsonify({'ok': True, 'printed': True})
    except Exception as e:
        return jsonify({'error': f'error inesperado: {e}'}), 500

@app.route('/api/routes', methods=['GET'])
def routes_list():
    return jsonify({'routes': [{'rule': r.rule, 'methods': list(r.methods)} for r in app.url_map.iter_rules()]})

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
    seed_products_from_config()
    backfill_product_details_from_config()
    seed_admin_users_from_env()
    start_background_tasks()
    try:
        print('Rutas registradas:')
        for r in app.url_map.iter_rules():
            print(' -', r.rule, list(r.methods))
    except Exception:
        pass
    print(f"Servidor Flask ejecutándose en http://localhost:{PORT}/ (raíz: {BASE_DIR})")
    # Escuchar en IPv4 para máxima compatibilidad en Windows
    app.run(host='0.0.0.0', port=PORT)
