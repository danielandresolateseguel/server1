import sqlite3

try:
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    
    # 1. Fix 'cancelled' -> 'cancelado' (fixing my previous mistake)
    cur.execute("UPDATE orders SET status = 'cancelado' WHERE status = 'cancelled'")
    print(f"Fixed {cur.rowcount} orders from 'cancelled' to 'cancelado'")
    
    # 2. Cancel any other active orders (not entregado or cancelado)
    # Note: Using Spanish statuses now
    cur.execute("UPDATE orders SET status = 'cancelado' WHERE status NOT IN ('entregado', 'cancelado')")
    print(f"Cancelled {cur.rowcount} remaining active orders")
    
    conn.commit()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
