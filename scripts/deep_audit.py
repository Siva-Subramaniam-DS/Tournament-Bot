import os
import re
import ast
import inspect
import sys

def audit_codebase():
    results = {
        "bugs": [],
        "performance_issues": [],
        "security_issues": [],
        "schema_mismatches": [],
        "discord_issues": [],
        "improvements": []
    }
    
    files = [
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
    
    for fpath in files:
        if not os.path.exists(fpath):
            continue
        with open(fpath, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            content = "".join(lines)
            
        # Check 1: requests.get/post inside async functions (blocking event loop)
        tree = ast.parse(content, filename=fpath)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef):
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Attribute):
                            if isinstance(child.func.value, ast.Name) and child.func.value.id == 'requests':
                                results["performance_issues"].append(
                                    f"[{fpath}:{child.lineno}] Synchronous `requests.{child.func.attr}` called inside async function `{node.name}`. Blocks Discord heartbeat!"
                                )
                            elif child.func.attr == 'sleep' and isinstance(child.func.value, ast.Name) and child.func.value.id == 'time':
                                results["performance_issues"].append(
                                    f"[{fpath}:{child.lineno}] Synchronous `time.sleep` called inside async function `{node.name}`. Blocks Discord heartbeat!"
                                )
                                
        # Check 2: Error handling / bare excepts / silent pass
        for idx, line in enumerate(lines):
            l = line.strip()
            if l == "except:" or l.startswith("except Exception:"):
                # check next line
                if idx + 1 < len(lines) and lines[idx+1].strip() == "pass":
                    # silent pass
                    pass
                    
            # Check for hardcoded URLs / tokens / IDs
            if "https://sheetdb.io/api/v1/" in line and "vlbn6vbc8vdbb" in line:
                results["security_issues"].append(
                    f"[{fpath}:{idx+1}] Hardcoded fallback SheetDB API URL with API ID `vlbn6vbc8vdbb` found."
                )
            if "1251442077561131059" in line:
                results["improvements"].append(
                    f"[{fpath}:{idx+1}] Hardcoded BOT_OWNER_ID fallback `1251442077561131059`."
                )

    return results

if __name__ == "__main__":
    res = audit_codebase()
    for category, items in res.items():
        print(f"=== {category.upper()} ({len(items)}) ===")
        for item in items:
            print(f"  * {item}")
