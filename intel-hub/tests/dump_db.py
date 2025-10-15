import sqlite3

conn = sqlite3.connect("intel.db")
cur = conn.cursor()

# 打印表结构
cur.execute("PRAGMA table_info(events);")
print("表结构:", cur.fetchall())

# 打印前 10 条数据
cur.execute("SELECT * FROM events LIMIT 10;")
rows = cur.fetchall()
for row in rows:
    print(row)

conn.close()