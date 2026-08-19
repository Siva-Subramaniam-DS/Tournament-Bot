import re
import json

with open('main.py', 'r', encoding='utf-8') as f:
    code = f.read()

# 1. Find all table references
tables = set(re.findall(r'supabase_client\.table\([\'"](\w+)[\'"]\)', code))
print("Tables accessed in main.py:", tables)

# 2. For each table, find all operations (select, insert, update, upsert, delete)
for table in sorted(tables):
    print(f"\n================ TABLE: {table} ================")
    # Pattern to match chained operations on supabase_client.table(table)
    pattern = rf'supabase_client\.table\([\'"]{table}[\'"]\)([\s\S]*?)(?:\.execute\(\)|\n\s*\n|[;])'
    matches = re.finditer(pattern, code)
    for m in matches:
        snippet = m.group(0)
        # trim snippet if too long
        lines = [l.strip() for l in snippet.split('\n') if l.strip()]
        print("--- SNIPPET ---")
        print('\n'.join(lines[:10]))
