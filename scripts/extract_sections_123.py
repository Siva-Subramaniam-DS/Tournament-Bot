import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('main.py', 'r', encoding='utf-8') as f:
    code = f.read()

def extract_code_block(start_line, end_line):
    lines = code.split('\n')
    return '\n'.join(lines[start_line-1:end_line])

print("=== 1. GuildConfig Python Mappings & Payloads ===")
print("--- Saving (Lines 1495-1550) ---")
print(extract_code_block(1495, 1550))

print("\n=== 2. Tournaments Python Mappings & Payloads ===")
print("--- Saving (Lines 1555-1610) ---")
print(extract_code_block(1555, 1610))

print("\n=== 3. Matches / Events Python Mappings & Payloads ===")
print("--- Loading (Lines 610-660) ---")
print(extract_code_block(610, 660))
print("--- Saving (Lines 760-880) ---")
print(extract_code_block(760, 880))
print("--- sync_to_supabase Matches/MatchStaff/StaffStats (Lines 1415-1485) ---")
print(extract_code_block(1415, 1485))
