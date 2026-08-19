import re
import sys

# Set stdout to utf-8
sys.stdout.reconfigure(encoding='utf-8')

with open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

def print_section(start, end, label=""):
    print(f"\n==================== {label} (Lines {start}-{end}) ====================")
    for i in range(start - 1, min(end, len(lines))):
        print(f"{i+1:5d}: {lines[i]}", end='')

print_section(130, 220, "GuildConfig Loading / Reading")
print_section(605, 680, "Matches / Events Loading")
print_section(755, 910, "save_event_to_supabase (Matches / Events)")
print_section(980, 1045, "Deadlines Supabase")
print_section(1415, 1635, "sync_to_supabase / GuildConfig / Tournaments")
print_section(10190, 10225, "Players & Teams updates")
print_section(10555, 10580, "GuildConfig Delete")
print_section(10680, 10790, "Tournaments Loading & Saving")
print_section(11445, 11555, "Tournament Deletion & Cascades")
