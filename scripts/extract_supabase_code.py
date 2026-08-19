import re
import sys

sys.stdout.reconfigure(encoding='utf-8')

with open('main.py', 'r', encoding='utf-8') as f:
    code = f.read()

# Let's find all dictionary literals passed to upsert, insert, update or constructed for supabase
# Specifically around lines 130-200, 750-900, 980-1045, 1400-1635, 10190-10225, 10560-10790, 11445-11555

def extract_code_block(start_line, end_line):
    lines = code.split('\n')
    return '\n'.join(lines[start_line-1:end_line])

print("=== 1. GuildConfig Python Mappings & Payloads ===")
print("--- Loading (Lines 136-189) ---")
print(extract_code_block(136, 189))
print("--- Saving (Lines 1495-1550) ---")
print(extract_code_block(1495, 1550))

print("\n=== 2. Tournaments Python Mappings & Payloads ===")
print("--- Saving (Lines 1555-1605) ---")
print(extract_code_block(1555, 1605))
print("--- Loading (Lines 10680-10770) ---")
print(extract_code_block(10680, 10770))

print("\n=== 3. Matches / Events Python Mappings & Payloads ===")
print("--- Loading (Lines 610-660) ---")
print(extract_code_block(610, 660))
print("--- Saving (Lines 760-880) ---")
print(extract_code_block(760, 880))
print("--- sync_to_supabase Matches/MatchStaff/StaffStats (Lines 1415-1485) ---")
print(extract_code_block(1415, 1485))

print("\n=== 4. Deadlines Python Mappings & Payloads ===")
print("--- Loading (Lines 985-1015) ---")
print(extract_code_block(985, 1015))
print("--- Saving (Lines 1025-1045) ---")
print(extract_code_block(1025, 1045))

print("\n=== 5. Players & Teams Updates (Lines 10195-10220) ===")
print(extract_code_block(10195, 10220))

print("\n=== 6. Tournament Deletion & Cascades (Lines 11450-11550) ===")
print(extract_code_block(11450, 11550))
