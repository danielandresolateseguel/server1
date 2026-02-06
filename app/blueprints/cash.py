import json
import csv
import io
from datetime import datetime
from flask import Blueprint, request, jsonify, session, make_response
from app.database import get_db
from app.utils import is_authed, check_csrf

bp = Blueprint('cash', __name__, url_prefix='/api/cash')

@bp.route('/session', methods=['GET'])
def cash_session_get():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, tenant_slug, opened_at, opened_by, opening_amount, notes_open, closed_at, closed_by, closing_amount, notes_close FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    row = cur.fetchone()
    if not row:
        return jsonify({'active': False})
    sess = dict(row)
    opened_at = sess['opened_at']
    cur.execute(
        "SELECT COALESCE(SUM(o.total),0), COALESCE(SUM(COALESCE(o.tip_amount, 0)),0), COALESCE(COUNT(*),0), COALESCE(SUM(COALESCE(o.shipping_cost, 0)),0) FROM orders o "
        "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
        "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ?",
        (tenant_slug, opened_at)
    )
    agg = cur.fetchone() or (0, 0, 0, 0)
    base_delivered_total = int(agg[0] or 0)
    tip_total = int(agg[1] or 0)
    delivered_total = base_delivered_total + tip_total
    delivered_count = int(agg[2] or 0)
    shipping_total = int(agg[3] or 0)
    
    cur.execute("SELECT type, payment_method, SUM(amount) FROM cash_movements WHERE session_id = ? GROUP BY type, payment_method", (sess['id'],))
    rows_mov = cur.fetchall()
    
    breakdown = {
        'efectivo': int(sess['opening_amount']), 
        'pos': 0, 
        'transferencia': 0, 
        'otros': 0
    }
    entradas = 0
    salidas = 0
    
    for r in rows_mov:
        mtype = r[0] 
        pm = (r[1] or '').strip().lower() 
        amt = int(r[2] or 0)
        
        if mtype == 'entrada':
            entradas += amt
            if 'pos' in pm or 'qr' in pm or 'tarjeta' in pm:
                breakdown['pos'] += amt
            elif 'transferencia' in pm:
                breakdown['transferencia'] += amt
            elif 'otros' in pm:
                breakdown['otros'] += amt
            else:
                breakdown['efectivo'] += amt
        elif mtype == 'salida':
            salidas += amt
            if 'pos' in pm or 'qr' in pm or 'tarjeta' in pm:
                breakdown['pos'] -= amt
            elif 'transferencia' in pm:
                breakdown['transferencia'] -= amt
            elif 'otros' in pm:
                breakdown['otros'] -= amt
            else:
                breakdown['efectivo'] -= amt

    theoretical_cash = int(sess['opening_amount']) + entradas - salidas
    return jsonify({
        'active': True, 
        'session': sess, 
        'summary': {
            'delivered_count': delivered_count, 
            'delivered_total': delivered_total, 
            'base_delivered_total': base_delivered_total, 
            'tip_total': tip_total, 
            'shipping_total': shipping_total, 
            'entradas': entradas, 
            'salidas': salidas, 
            'theoretical_cash': theoretical_cash,
            'theoretical_breakdown': breakdown
        }
    })

@bp.route('/open', methods=['POST'])
def cash_open():
    if not is_authed(): return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf(): return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    tenant_slug = (payload.get('tenant_slug') or request.args.get('tenant_slug') or 'gastronomia-local1')
    opening_amount = int(payload.get('opening_amount') or 0)
    notes_open = (payload.get('notes') or '').strip()
    actor = session.get('admin_user') or ''
    now = datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    if cur.fetchone():
        return jsonify({'error': 'ya existe una sesión de caja abierta'}), 400
    cur.execute("INSERT INTO cash_sessions (tenant_slug, opened_at, opened_by, opening_amount, notes_open) VALUES (?, ?, ?, ?, ?)", (tenant_slug, now, actor, opening_amount, notes_open))
    conn.commit()
    sid = cur.lastrowid
    return jsonify({'session_id': sid, 'tenant_slug': tenant_slug, 'opened_at': now, 'opening_amount': opening_amount})

@bp.route('/close', methods=['POST'])
def cash_close():
    if not is_authed(): return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf(): return jsonify({'error': 'csrf inválido'}), 403
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
        return jsonify({'error': 'no hay sesión de caja abierta'}), 400
    sid = int(row[0])
    opened_at = str(row[1])
    opening_amount = int(row[2] or 0)
    
    cur.execute(
        "SELECT COALESCE(SUM(o.total),0), COALESCE(SUM(COALESCE(o.tip_amount, 0)),0), COALESCE(SUM(COALESCE(o.shipping_cost, 0)),0) FROM orders o "
        "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
        "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ?",
        (tenant_slug, opened_at, now)
    )
    row_totals = cur.fetchone() or (0, 0, 0)
    base_delivered_total = int(row_totals[0] or 0)
    tip_total = int(row_totals[1] or 0)
    shipping_total = int(row_totals[2] or 0)
    delivered_total = base_delivered_total + tip_total
    
    cur.execute("SELECT type, payment_method, SUM(amount) FROM cash_movements WHERE session_id = ? GROUP BY type, payment_method", (sid,))
    rows_mov = cur.fetchall()
    
    breakdown = {'efectivo': opening_amount, 'pos': 0, 'transferencia': 0, 'otros': 0}
    entradas = 0
    salidas = 0
    
    for r in rows_mov:
        mtype = r[0]
        pm = (r[1] or '').strip().lower()
        amt = int(r[2] or 0)
        if mtype == 'entrada':
            entradas += amt
            if pm == 'pos': breakdown['pos'] += amt
            elif pm == 'transferencia': breakdown['transferencia'] += amt
            elif pm == 'otros': breakdown['otros'] += amt
            else: breakdown['efectivo'] += amt
        elif mtype == 'salida':
            salidas += amt
            if pm == 'pos': breakdown['pos'] -= amt
            elif pm == 'transferencia': breakdown['transferencia'] -= amt
            elif pm == 'otros': breakdown['otros'] -= amt
            else: breakdown['efectivo'] -= amt

    theoretical_cash = opening_amount + entradas - salidas
    closing_diff = closing_amount - theoretical_cash
    
    declared_breakdown = payload.get('breakdown') or {}
    closing_metadata = json.dumps({'declared_breakdown': declared_breakdown})
    
    cur.execute("UPDATE cash_sessions SET closed_at = ?, closed_by = ?, closing_amount = ?, notes_close = ?, closing_diff = ?, closing_metadata = ? WHERE id = ?", (now, actor, closing_amount, notes_close, closing_diff, closing_metadata, sid))
    conn.commit()
    
    return jsonify({
        'session_id': sid, 
        'tenant_slug': tenant_slug, 
        'opened_at': opened_at, 
        'closed_at': now, 
        'closing_amount': closing_amount, 
        'summary': {
            'opening_amount': opening_amount, 
            'entradas': entradas, 
            'salidas': salidas, 
            'delivered_total': delivered_total, 
            'base_delivered_total': base_delivered_total, 
            'tip_total': tip_total, 
            'shipping_total': shipping_total, 
            'theoretical_cash': theoretical_cash, 
            'closing_diff': closing_diff,
            'theoretical_breakdown': breakdown,
            'declared_breakdown': declared_breakdown
        }
    })

@bp.route('/movements', methods=['GET'])
def cash_movements_list():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    session_id = request.args.get('session_id')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    try:
        sid = int(session_id or 0)
    except:
        sid = 0
    conn = get_db()
    cur = conn.cursor()
    movements = []
    if sid > 0:
        cur.execute("SELECT id, session_id, type, amount, note, actor, created_at FROM cash_movements WHERE session_id = ? ORDER BY id ASC", (sid,))
        movements = [dict(r) for r in cur.fetchall()]
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
        movements = [dict(r) for r in cur.fetchall()]
    return jsonify({'tenant_slug': tenant_slug, 'session_id': sid, 'movements': movements})

@bp.route('/movement', methods=['POST'])
def cash_movement():
    if not is_authed(): return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf(): return jsonify({'error': 'csrf inválido'}), 403
    payload = request.get_json(silent=True) or {}
    tenant_slug = (payload.get('tenant_slug') or request.args.get('tenant_slug') or 'gastronomia-local1')
    mtype = (payload.get('type') or '').strip().lower()
    amount = int(payload.get('amount') or 0)
    note = (payload.get('note') or '').strip()
    if mtype not in ('entrada','salida'): return jsonify({'error': 'tipo inválido'}), 400
    if amount <= 0: return jsonify({'error': 'monto inválido'}), 400
    actor = session.get('admin_user') or ''
    now = datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
    row = cur.fetchone()
    if not row: return jsonify({'error': 'no hay sesión de caja abierta'}), 400
    sid = int(row[0])
    cur.execute("INSERT INTO cash_movements (session_id, type, amount, note, actor, created_at, payment_method) VALUES (?, ?, ?, ?, ?, ?, ?)", (sid, mtype, amount, note, actor, now, (payload.get('payment_method') or '').strip()))
    conn.commit()
    return jsonify({'session_id': sid, 'type': mtype, 'amount': amount, 'note': note, 'created_at': now})

@bp.route('/session/orders', methods=['GET'])
def cash_session_orders():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    session_id = request.args.get('session_id')
    to_date = request.args.get('to')
    try:
        sid = int(session_id or 0)
    except:
        sid = 0
    conn = get_db()
    cur = conn.cursor()
    opened_at = None
    closed_at = None
    if sid > 0:
        cur.execute("SELECT opened_at, closed_at FROM cash_sessions WHERE id = ? AND tenant_slug = ?", (sid, tenant_slug))
        row = cur.fetchone()
        if row:
            opened_at = str(row[0] or '')
            closed_at = str(row[1] or '')
    else:
        cur.execute("SELECT id, opened_at FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NULL ORDER BY opened_at DESC LIMIT 1", (tenant_slug,))
        row = cur.fetchone()
        if row:
            sid = int(row[0])
            opened_at = str(row[1] or '')
            
    if not opened_at:
        return jsonify({'orders': []})
        
    end_at = to_date if to_date else (closed_at or datetime.utcnow().isoformat())
    base = (
        "SELECT o.id, o.created_at, o.total, o.payment_method FROM orders o "
        "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
        "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ? "
        "ORDER BY o.id DESC"
    )
    cur.execute(base, (tenant_slug, opened_at, end_at))
    rows = cur.fetchall()
    return jsonify({'orders': [ {'id': int(r[0]), 'created_at': r[1], 'total': int(r[2] or 0), 'payment_method': r[3] } for r in rows ], 'session_id': sid, 'from': opened_at, 'to': end_at})

@bp.route('/sessions', methods=['GET'])
def cash_sessions_list():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    limit = int(request.args.get('limit') or 50)
    offset = int(request.args.get('offset') or 0)
    date_field = (request.args.get('date_field') or 'closed').strip().lower()
    if date_field not in ('closed', 'opened'): date_field = 'closed'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10: return s + ('T23:59:59' if end else 'T00:00:00')
        except: pass
        return s
        
    from_date = _norm_date(from_date, end=False)
    to_date = _norm_date(to_date, end=True)
    
    conn = get_db()
    cur = conn.cursor()
    base = "SELECT id, tenant_slug, opened_at, opened_by, opening_amount, notes_open, closed_at, closed_by, closing_amount, notes_close, closing_diff, closing_metadata FROM cash_sessions WHERE tenant_slug = ? AND closed_at IS NOT NULL"
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
            "SELECT COALESCE(SUM(o.total),0), COALESCE(SUM(COALESCE(o.tip_amount, 0)),0), COALESCE(COUNT(*),0), COALESCE(SUM(COALESCE(o.shipping_cost, 0)),0) FROM orders o "
            "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
            "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ?",
            (tenant_slug, opened_at, closed_at)
        )
        trow = cur.fetchone() or (0,0,0,0)
        base_delivered_total = int(trow[0] or 0)
        tip_total = int(trow[1] or 0)
        delivered_total = base_delivered_total + tip_total
        delivered_count = int(trow[2] or 0)
        shipping_total = int(trow[3] or 0)
        
        cur.execute("SELECT COALESCE(SUM(CASE WHEN type='entrada' THEN amount ELSE 0 END),0), COALESCE(SUM(CASE WHEN type='salida' THEN amount ELSE 0 END),0) FROM cash_movements WHERE session_id = ?", (sid,))
        mrow = cur.fetchone() or (0,0)
        entradas = int(mrow[0] or 0)
        salidas = int(mrow[1] or 0)
        theoretical_cash = int(s.get('opening_amount') or 0) + entradas - salidas
        
        cur.execute("SELECT type, payment_method, SUM(amount) FROM cash_movements WHERE session_id = ? GROUP BY type, payment_method", (sid,))
        rows_mov = cur.fetchall()
        breakdown = {'efectivo': int(s.get('opening_amount') or 0), 'pos': 0, 'transferencia': 0, 'otros': 0}
        for rm in rows_mov:
            mtype = rm[0]
            pm = (rm[1] or '').strip().lower()
            amt = int(rm[2] or 0)
            if mtype == 'entrada':
                if 'pos' in pm or 'qr' in pm or 'tarjeta' in pm: breakdown['pos'] += amt
                elif 'transferencia' in pm: breakdown['transferencia'] += amt
                elif 'otros' in pm: breakdown['otros'] += amt
                else: breakdown['efectivo'] += amt
            elif mtype == 'salida':
                if 'pos' in pm or 'qr' in pm or 'tarjeta' in pm: breakdown['pos'] -= amt
                elif 'transferencia' in pm: breakdown['transferencia'] -= amt
                elif 'otros' in pm: breakdown['otros'] -= amt
                else: breakdown['efectivo'] -= amt

        s['summary'] = {
            'delivered_total': delivered_total,
            'delivered_count': delivered_count,
            'entradas': entradas,
            'salidas': salidas,
            'theoretical_cash': theoretical_cash,
            'theoretical_breakdown': breakdown,
            'base_delivered_total': base_delivered_total,
            'tip_total': tip_total,
            'shipping_total': shipping_total,
            'closing_diff': int(s.get('closing_diff') or 0)
        }
        sessions.append(s)
        
    return jsonify({'sessions': sessions, 'limit': limit, 'offset': offset, 'count': len(sessions)})

@bp.route('/sessions/export.csv', methods=['GET'])
def cash_sessions_export_csv():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    date_field = (request.args.get('date_field') or 'closed').strip().lower()
    if date_field not in ('closed', 'opened'): date_field = 'closed'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    
    def _norm_date(s, end=False):
        try:
            if s and len(s) == 10: return s + ('T23:59:59' if end else 'T00:00:00')
        except: pass
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
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['tenant_slug', 'opened_at', 'opened_by', 'opening_amount', 'notes_open', 'closed_at', 'closed_by', 'closing_amount', 'notes_close', 'base_delivered_total', 'tip_total', 'shipping_total', 'delivered_total', 'entradas', 'salidas', 'theoretical_cash', 'closing_diff'])
    
    for r in rows:
        s = dict(r)
        sid = int(s['id'])
        opened_at = s.get('opened_at')
        closed_at = s.get('closed_at')
        
        cur.execute(
            "SELECT COALESCE(SUM(o.total),0), COALESCE(SUM(COALESCE(o.tip_amount, 0)),0), COALESCE(SUM(COALESCE(o.shipping_cost, 0)),0) FROM orders o "
            "JOIN (SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id) h ON h.order_id = o.id "
            "WHERE o.tenant_slug = ? AND o.status = 'entregado' AND h.last_change >= ? AND h.last_change <= ?",
            (tenant_slug, opened_at, closed_at)
        )
        trow = cur.fetchone() or (0,0,0)
        base_delivered_total = int(trow[0] or 0)
        tip_total = int(trow[1] or 0)
        shipping_total = int(trow[2] or 0)
        delivered_total = base_delivered_total + tip_total
        
        cur.execute("SELECT COALESCE(SUM(CASE WHEN type='entrada' THEN amount ELSE 0 END),0), COALESCE(SUM(CASE WHEN type='salida' THEN amount ELSE 0 END),0) FROM cash_movements WHERE session_id = ?", (sid,))
        mrow = cur.fetchone() or (0,0)
        entradas = int(mrow[0] or 0)
        salidas = int(mrow[1] or 0)
        theoretical_cash = int(s.get('opening_amount') or 0) + entradas - salidas
        
        writer.writerow([
            s.get('tenant_slug'), s.get('opened_at'), s.get('opened_by'), int(s.get('opening_amount') or 0), s.get('notes_open'), s.get('closed_at'), s.get('closed_by'), int(s.get('closing_amount') or 0), s.get('notes_close'), base_delivered_total, tip_total, shipping_total, delivered_total, entradas, salidas, theoretical_cash, int(s.get('closing_diff') or 0)
        ])
        
    resp = make_response(output.getvalue())
    resp.headers['Content-Type'] = 'text/csv'
    resp.headers['Content-Disposition'] = 'attachment; filename="cash_sessions.csv"'
    return resp
