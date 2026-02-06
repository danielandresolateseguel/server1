import sqlite3
import json

DB_PATH = 'orders.db'

def run():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    ids_to_check = [
        'plato1', 'plato2', 'plato3', 'plato4', 
        'dest1', 'dest2', 'dest3', 'dest4', 
        'i1', 'i1-2', 'i2', 'i2-2', 'i3', 'i3-2'
    ]

    print(f"Checking {len(ids_to_check)} products in {DB_PATH} for tenant 'gastronomia-local1'...")
    
    placeholders = ','.join('?' for _ in ids_to_check)
    query = f"""
        SELECT product_id, name, active, variants_json 
        FROM products 
        WHERE tenant_slug = 'gastronomia-local1' 
        AND product_id IN ({placeholders})
    """
    
    cur.execute(query, ids_to_check)
    rows = cur.fetchall()
    
    found_ids = set()
    for r in rows:
        pid = r['product_id']
        found_ids.add(pid)
        print(f"FOUND: {pid} | Name: {r['name']} | Active: {r['active']}")
        print(f"  Variants: {r['variants_json']}")
        print("-" * 40)

    missing = set(ids_to_check) - found_ids
    if missing:
        print(f"\nMISSING IDs: {missing}")
    else:
        print("\nAll IDs found.")

    conn.close()

if __name__ == '__main__':
    run()
