
import sqlite3
import json
from datetime import datetime

db_path = 'orders.db'
conn = sqlite3.connect(db_path)
cur = conn.cursor()

print("--- Tenants ---")
try:
    cur.execute("SELECT * FROM tenants")
    for r in cur.fetchall():
        print(r)
except Exception as e:
    print(f"Error reading tenants: {e}")

print("\n--- Simulating Order for 'planeta-pancho' ---")
# Manually insert an order to see if constraints or schema allow it
try:
    slug = 'planeta-pancho'
    order_type = 'mesa'
    table = '5'
    total = 1500
    status = 'pendiente'
    now = datetime.utcnow().isoformat()
    
    sql = """
    INSERT INTO orders (tenant_slug, customer_name, order_type, table_number, status, total, created_at)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    RETURNING id
    """
    # Note: RETURNING might not work in older sqlite versions, fallback to lastrowid if needed
    try:
        cur.execute(sql, (slug, 'Test User', order_type, table, status, total, now))
        new_id = cur.fetchone()[0]
        print(f"Order created successfully! ID: {new_id}")
    except sqlite3.OperationalError:
        # Fallback for older sqlite
        cur.execute("""
        INSERT INTO orders (tenant_slug, customer_name, order_type, table_number, status, total, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (slug, 'Test User', order_type, table, status, total, now))
        new_id = cur.lastrowid
        print(f"Order created successfully (fallback)! ID: {new_id}")

    conn.commit()
    
    # Verify it exists
    cur.execute("SELECT * FROM orders WHERE id = ?", (new_id,))
    print("Fetched Order:", cur.fetchone())

except Exception as e:
    print(f"Failed to create order: {e}")

conn.close()
