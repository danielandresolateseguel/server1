import sqlite3

conn = sqlite3.connect('orders.db')
cursor = conn.cursor()
cursor.execute("SELECT product_id, name, stock FROM products WHERE tenant_slug='gastronomia-local1'")
rows = cursor.fetchall()
for row in rows:
    print(row)
conn.close()
