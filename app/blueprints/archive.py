from flask import Blueprint, request, jsonify, session, Response
from app.database import get_db
from app.utils import is_authed, check_csrf
from datetime import datetime, timedelta, timezone
import re
import unicodedata
import io
import csv
import json

bp = Blueprint('archive', __name__, url_prefix='/api')

@bp.route('/archive', methods=['GET'])
def get_archive():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    a_type = request.args.get('type')
    limit = int(request.args.get('limit') or 100)
    offset = int(request.args.get('offset') or 0)
    q = request.args.get('q')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    order_type = request.args.get('order_type')
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
    if order_type:
        base += " AND o.order_type = ?"
        params.append(order_type)
    if q:
        try:
            qid = int(q)
            base += " AND o.id = ?"
            params.append(qid)
        except Exception:
            nq = re.sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=re.IGNORECASE).strip()
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
    if order_type:
        count_sql += " AND o.order_type = ?"
        count_params.append(order_type)
    if q:
        try:
            qid = int(q)
            count_sql += " AND o.id = ?"
            count_params.append(qid)
        except Exception:
            nq = re.sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=re.IGNORECASE).strip()
            like = f"%{nq.lower()}%"
            count_sql += " AND (LOWER(COALESCE(o.address_json,'')) LIKE ? OR LOWER(COALESCE(o.table_number,'')) LIKE ? OR LOWER(COALESCE(o.customer_name,'')) LIKE ?)"
            count_params.extend([like, like, like])
    cur.execute(count_sql, count_params)
    total_count = int(cur.fetchone()[0])
    data = [dict(r) for r in rows]
    if q:
        try:
            int(q)
        except Exception:
            def _norm(s):
                s = str(s or '').lower()
                return ''.join(c for c in unicodedata.normalize('NFKD', s) if not unicodedata.combining(c))
            nq = re.sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=re.IGNORECASE).strip()
            nq = _norm(nq)
            data = [r for r in data if (nq in _norm(r.get('address_json')) or nq in _norm(r.get('table_number')) or nq in _norm(r.get('customer_name')))]
    return jsonify({'archives': data, 'count': len(data), 'limit': limit, 'offset': offset, 'total_count': total_count})

@bp.route('/archive/eligible_count', methods=['GET'])
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
    return jsonify({'count': int(n), 'type': a_type, 'tenant_slug': tenant_slug or None, 'hours': hours})

@bp.route('/archive/export.csv', methods=['GET'])
@bp.route('/archive/export', methods=['GET'])
def archive_export():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    a_type = request.args.get('type')
    q = request.args.get('q')
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    order_type = request.args.get('order_type')
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
    if order_type:
        base += " AND o.order_type = ?"
        params.append(order_type)
    if q:
        try:
            qid = int(q)
            base += " AND o.id = ?"
            params.append(qid)
        except Exception:
            nq = re.sub(r"^(destino|direccion|dir)\s*:\s*", "", str(q), flags=re.IGNORECASE).strip()
            like = f"%{nq.lower()}%"
            base += " AND (LOWER(COALESCE(o.address_json,'')) LIKE ? OR LOWER(COALESCE(o.table_number,'')) LIKE ? OR LOWER(COALESCE(o.customer_name,'')) LIKE ?)"
            params.extend([like, like, like])
    base += " ORDER BY o.id DESC"
    cur.execute(base, params)
    rows = cur.fetchall()
    
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "created_at", "order_type", "destination", "customer_phone", "total", "status", "archived_at", "customer_name", "last_status", "last_change", "payment_status"])
    for r in rows:
        dest = r[3] if r[2] == 'mesa' else (r[4] or '')
        total = int(r[5] or 0)
        writer.writerow([r[0], r[1], r[2], dest, r[9] or '', total, r[6], r[7], r[8], r[10] or '', r[11] or '', r[12] or ''])
    resp_val = output.getvalue()
    
    def _safe(s):
        return ''.join(c for c in str(s or '') if c.isalnum() or c in ('-', '_'))
    df = 'arch' if date_field == 'archived' else 'order'
    def _dpart(d):
        try:
            return str(d or 'all')[:10].replace('T','').replace(':','')
        except Exception:
            return 'all'
    fname = f"archives_{_safe(tenant_slug or 'tenant')}_{df}_{_dpart(from_date)}_{_dpart(to_date)}_{_safe(a_type or 'all')}.csv"
    return Response(resp_val, mimetype='text/csv', headers={'Content-Disposition': f'attachment; filename="{fname}"'})

@bp.route('/archive/metrics', methods=['GET'])
def archive_metrics():
    tenant_slug = request.args.get('tenant_slug') or request.args.get('slug') or 'gastronomia-local1'
    from_date = request.args.get('from')
    to_date = request.args.get('to')
    order_type = request.args.get('order_type')
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
        {" AND o.order_type = ?" if order_type else ''}
    """
    # Delivered metrics
    params_del = [tenant_slug, 'delivered'] + ([from_date] if from_date else []) + ([to_date] if to_date else []) + ([order_type] if order_type else [])
    cur.execute(base, params_del)
    rows_del = cur.fetchall()
    delivered_count = len(rows_del)
    delivered_total = int(sum(int(r[0] or 0) for r in rows_del))
    tip = (delivered_total + 5) // 10
    delivered_total_with_tip = delivered_total + tip
    # Canceled metrics
    params_can = [tenant_slug, 'canceled'] + ([from_date] if from_date else []) + ([to_date] if to_date else []) + ([order_type] if order_type else [])
    cur.execute(base, params_can)
    rows_can = cur.fetchall()
    canceled_count = len(rows_can)
    canceled_total = int(sum(int(r[0] or 0) for r in rows_can))
    return jsonify({
        'delivered_count': delivered_count,
        'delivered_total': delivered_total,
        'delivered_tip_10': tip,
        'delivered_total_with_tip': delivered_total_with_tip,
        'canceled_count': canceled_count,
        'canceled_total': canceled_total
    })

@bp.route('/archive', methods=['POST'])
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
    if a_type not in ('delivered', 'canceled', 'reset'):
        return jsonify({'error': 'type inválido'}), 400
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id, tenant_slug, status FROM orders WHERE id = ?", (order_id,))
    r = cur.fetchone()
    if not r:
        return jsonify({'error': 'orden no encontrada'}), 404
    tenant_slug = r[1]
    cur.execute(
        "INSERT OR IGNORE INTO archived_orders (order_id, tenant_slug, type, archived_at) VALUES (?, ?, ?, ?)",
        (order_id, tenant_slug, a_type, datetime.utcnow().isoformat())
    )
    conn.commit()
    return jsonify({'ok': True, 'order_id': order_id, 'type': a_type})

@bp.route('/archive/reset', methods=['POST'])
def reset_active_orders():
    if not is_authed():
        return jsonify({'error': 'no autorizado'}), 401
    if not check_csrf():
        return jsonify({'error': 'csrf inválido'}), 403
    
    payload = request.get_json(silent=True) or {}
    tenant_slug = payload.get('tenant_slug')
    if not tenant_slug:
        return jsonify({'error': 'tenant_slug requerido'}), 400

    conn = get_db()
    cur = conn.cursor()
    
    # Select all active orders (not in archived_orders) for this tenant
    cur.execute("""
        SELECT id FROM orders 
        WHERE tenant_slug = ? 
        AND id NOT IN (SELECT order_id FROM archived_orders)
    """, (tenant_slug,))
    
    rows = cur.fetchall()
    count = 0
    now_iso = datetime.utcnow().isoformat()
    
    for row in rows:
        order_id = row[0]
        cur.execute(
            "INSERT OR IGNORE INTO archived_orders (order_id, tenant_slug, type, archived_at) VALUES (?, ?, 'reset', ?)",
            (order_id, tenant_slug, now_iso)
        )
        count += 1
        
    conn.commit()
    return jsonify({'ok': True, 'count': count})

@bp.route('/metrics', methods=['GET'])
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
        cur.execute("SELECT COUNT(*) FROM orders WHERE tenant_slug = ? AND status NOT IN ('entregado','cancelado') AND id NOT IN (SELECT order_id FROM archived_orders)", (tenant_slug,))
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
                try:
                    if not s: return None
                    dt = None
                    if isinstance(s, str):
                        dt = datetime.fromisoformat(s)
                    elif isinstance(s, datetime):
                        dt = s
                    
                    if dt:
                        # Normalize to naive UTC
                        if dt.tzinfo is not None:
                            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
                        return dt
                    return None
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
        except Exception as e:
            print(f"Error calculating average metrics: {e}")
            avg_prep = 0
            avg_listo = 0
            avg_entregado = 0

        resp = jsonify({
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
        resp.headers['Cache-Control'] = 'no-store, no-cache, must-revalidate, max-age=0'
        resp.headers['Pragma'] = 'no-cache'
        resp.headers['Expires'] = '0'
        return resp
    
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


