import re

with open('core/database.py', encoding='utf-8') as f:
    content = f.read()

tables1 = set(re.findall(r"table\([\'\"]([^\'\"]+)[\'\"]\)", content))
tables2 = set(re.findall(r"supabase_safe_upsert\([\'\"]([^\'\"]+)[\'\"]", content))
all_tables = tables1.union(tables2)

print("Tables referenced in core/database.py:")
for t in sorted(all_tables):
    print("-", t)
