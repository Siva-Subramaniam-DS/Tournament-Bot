import re

with open('core/database.py', encoding='utf-8') as f:
    lines = f.readlines()

for i, line in enumerate(lines):
    if any(tbl in line for tbl in ["GuildConfig", "StaffStats", "Tournaments", "Events", "Deadlines"]):
        print(f"Line {i+1}: {line.strip()[:100]}")
