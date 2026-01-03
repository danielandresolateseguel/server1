import sqlite3
import datetime

try:
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    
    # Get active orders first
    cur.execute("SELECT id, status FROM orders WHERE status NOT IN ('completed', 'cancelled')")
    rows = cur.fetchall()
    print(f"Found {len(rows)} active orders:")
    for row in rows:
        print(row)
        
    # Cancel them
    if rows:
        cur.execute("UPDATE orders SET status = 'cancelled' WHERE status NOT IN ('completed', 'cancelled')")
        print(f"Cancelled {cur.rowcount} orders.")
        conn.commit()
    else:
        print("No active orders found.")
        
    conn.close()
except Exception as e:
    print(f"Error: {e}")
