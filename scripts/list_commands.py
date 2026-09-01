import os
import ast

cogs = [
    "cogs/tournaments.py",
    "cogs/events.py",
    "cogs/listeners.py",
    "cogs/settings.py",
    "cogs/staff.py",
    "cogs/utilities.py"
]

print("=== LISTING ALL COMMANDS & VIEWS ===")
for cog_path in cogs:
    print(f"\n--- {cog_path} ---")
    with open(cog_path, "r", encoding="utf-8") as f:
        code = f.read()
    tree = ast.parse(code, filename=cog_path)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            base_names = [getattr(b, 'id', getattr(b, 'attr', '')) for b in node.bases]
            if 'View' in base_names or 'Modal' in base_names or 'Cog' in base_names or any('View' in b or 'Modal' in b for b in base_names):
                print(f"  Class: {node.name} (Bases: {base_names})")
        elif isinstance(node, ast.AsyncFunctionDef):
            for dec in node.decorator_list:
                dec_str = ""
                if isinstance(dec, ast.Call):
                    dec_str = getattr(dec.func, 'attr', '') or getattr(dec.func, 'id', '')
                elif isinstance(dec, ast.Attribute):
                    dec_str = dec.attr
                if dec_str in ('command', 'listener', 'hybrid_command'):
                    args = [a.arg for a in node.args.args]
                    print(f"  Command/Listener: @{dec_str} async def {node.name}({', '.join(args)})")

