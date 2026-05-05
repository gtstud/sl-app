import psycopg2

try:
    conn = psycopg2.connect("postgresql://test:test@localhost:15432/test")
    print("Connection successful!")
    conn.close()
except Exception as e:
    print(f"Connection failed: {e}")
