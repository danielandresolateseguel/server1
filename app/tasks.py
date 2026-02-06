import threading
import time
from datetime import datetime, timedelta
from flask import current_app

def _auto_archive_once_logic(conn):
    try:
        cur = conn.cursor()
        cutoff_dt = datetime.utcnow() - timedelta(hours=24)
        cutoff = cutoff_dt.isoformat()
        
        # 1. Archive delivered orders
        cur.execute(
            """
            SELECT o.id, o.tenant_slug
            FROM orders o
            JOIN (
              SELECT order_id, MAX(changed_at) AS last_change FROM order_status_history WHERE status = 'entregado' GROUP BY order_id
            ) h ON h.order_id = o.id
            LEFT JOIN archived_orders a ON a.order_id = o.id AND a.type = 'delivered'
            WHERE a.order_id IS NULL AND h.last_change <= ? AND o.payment_status = 'paid'
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
            
        # 2. Archive canceled orders
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

def start_background_tasks(app):
    if getattr(app, '_bg_started', False):
        return
    app._bg_started = True
    
    def loop():
        while True:
            try:
                # We need application context to access database config via get_db
                with app.app_context():
                    from app.database import get_db
                    conn = get_db()
                    _auto_archive_once_logic(conn)
            except Exception:
                pass
            time.sleep(300)
            
    t = threading.Thread(target=loop, daemon=True)
    t.start()
