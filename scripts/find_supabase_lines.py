import ast
import re

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines in main.py: {len(lines)}")

# Find all occurrences of supabase_client in main.py with line numbers and surrounding context
supabase_occurrences = []
for idx, line in enumerate(lines):
    if 'supabase_client' in line:
        supabase_occurrences.append((idx + 1, line.strip()))

print(f"Found {len(supabase_occurrences)} occurrences of supabase_client:")
for line_no, line_text in supabase_occurrences:
    print(f"Line {line_no:5d}: {line_text[:100]}")
