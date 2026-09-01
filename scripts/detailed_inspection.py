import os
import ast
import re

files_to_check = [
    "main.py",
    "core/config.py",
    "core/state.py",
    "core/database.py",
    "core/transcript.py",
    "core/image_generator.py",
    "cogs/tournaments.py",
    "cogs/events.py",
    "cogs/listeners.py",
    "cogs/settings.py",
    "cogs/staff.py",
    "cogs/utilities.py"
]

print("=== DEEP CODE INSPECTION ===")

for filepath in files_to_check:
    if not os.path.exists(filepath):
        continue
    with open(filepath, "r", encoding="utf-8") as f:
        code = f.read()
        lines = code.split("\n")
    
    # 1. Check for blocking calls in async def
    tree = ast.parse(code, filename=filepath)
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    # Check for Image.open, Image.save, requests.get/post, time.sleep
                    if isinstance(child.func, ast.Attribute):
                        attr = child.func.attr
                        val = child.func.value
                        val_id = getattr(val, 'id', None)
                        if val_id == 'requests':
                            print(f"[BLOCKING HTTP] {filepath}:{child.lineno} in async def {node.name}(): `requests.{attr}` is blocking.")
                        elif val_id == 'time' and attr == 'sleep':
                            print(f"[BLOCKING SLEEP] {filepath}:{child.lineno} in async def {node.name}(): `time.sleep` is blocking.")
                        elif val_id == 'Image' and attr in ('open', 'new'):
                            print(f"[POTENTIAL CPU BLOCK] {filepath}:{child.lineno} in async def {node.name}(): PIL `Image.{attr}` on event loop.")
                            
        # 2. Check for slash commands without defer that do network / heavy IO
        if isinstance(node, ast.AsyncFunctionDef):
            has_interaction = any(arg.arg in ('interaction', 'ctx') for arg in node.args.args)
            # check decorators
            is_slash = False
            for dec in node.decorator_list:
                if isinstance(dec, ast.Call):
                    dec_func = getattr(dec.func, 'attr', '')
                    if dec_func in ('command', 'callback'):
                        is_slash = True
                elif isinstance(dec, ast.Attribute) and dec.attr in ('command', 'callback'):
                    is_slash = True
                    
            if is_slash:
                # check if interaction.response.defer or interaction.response.send_message is in the function
                calls = []
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Attribute):
                            calls.append(child.func.attr)
                if 'defer' not in calls and ('requests' in code or 'fetch' in node.name or 'sync' in node.name):
                    # Potential timeout
                    pass

print("=== SCAN COMPLETE ===")
