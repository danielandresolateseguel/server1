import sqlite3
import os

try:
    conn = sqlite3.connect('orders.db')
    cur = conn.cursor()
    cur.execute("UPDATE cash_movements SET type='entrada' WHERE type='ingreso'")
    print(f"Updated {cur.rowcount} rows")
    conn.commit()
    conn.close()
except Exception as e:
    print(f"Error: {e}")
