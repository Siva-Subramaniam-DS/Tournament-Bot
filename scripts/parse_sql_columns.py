import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

# 1. Parse SQL tables and columns from supabase_migration.sql and supabase_schema.sql
def parse_sql_file(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        sql = f.read()

    # Find CREATE TABLE statements
    tables = {}
    table_blocks = re.findall(r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?["\']?(\w+)["\']?\s*\(([\s\S]*?)\);', sql, re.IGNORECASE)
    for tname, body in table_blocks:
        columns = []
        for line in body.split('\n'):
            line = line.strip()
            if not line or line.startswith('--') or line.startswith('CONSTRAINT') or line.startswith('PRIMARY') or line.startswith('UNIQUE'):
                continue
            col_match = re.match(r'["\']?(\w+)["\']?\s+([A-Za-z0-9_]+)', line)
            if col_match:
                col_name = col_match.group(1)
                # Ignore table-level keywords like PRIMARY, FOREIGN, CONSTRAINT, CHECK, UNIQUE
                if col_name.upper() not in ('PRIMARY', 'FOREIGN', 'CONSTRAINT', 'CHECK', 'UNIQUE'):
                    columns.append(col_name)
        tables[tname] = columns
    return tables

migration_tables = parse_sql_file('supabase_migration.sql')
schema_tables = parse_sql_file('supabase_schema.sql')
extension_tables = parse_sql_file('supabase_schema_extension.sql')

print("=== TABLES IN supabase_migration.sql ===")
for t, cols in migration_tables.items():
    print(f"Table '{t}' ({len(cols)} cols): {cols}")

print("\n=== TABLES IN supabase_schema.sql ===")
for t, cols in schema_tables.items():
    print(f"Table '{t}' ({len(cols)} cols): {cols}")

print("\n=== TABLES IN supabase_schema_extension.sql ===")
for t, cols in extension_tables.items():
    print(f"Table '{t}' ({len(cols)} cols): {cols}")
