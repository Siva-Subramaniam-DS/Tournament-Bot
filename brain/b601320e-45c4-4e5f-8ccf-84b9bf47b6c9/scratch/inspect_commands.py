import ast

with open("main.py", "r", encoding="utf-8") as f:
    source = f.read()

tree = ast.parse(source)

missing = []

class CommandVisitor(ast.NodeVisitor):
    def visit_AsyncFunctionDef(self, node):
        is_tree_command = False
        for decorator in node.decorator_list:
            # Check if it is @tree.command or @settings_group.command or @tournament_group.command or decorated with app_commands
            if isinstance(decorator, ast.Call):
                func = decorator.func
                # e.g. tree.command or settings_group.command
                if isinstance(func, ast.Attribute) and func.attr == "command":
                    is_tree_command = True
            elif isinstance(decorator, ast.Attribute) and decorator.attr == "command":
                is_tree_command = True
        
        if is_tree_command or node.name.startswith("event_") or node.name == "player_information":
            # Search for current_guild_id.set call inside the function body
            has_set = False
            for child in ast.walk(node):
                if isinstance(child, ast.Call):
                    if isinstance(child.func, ast.Attribute) and child.func.attr == "set":
                        if isinstance(child.func.value, ast.Name) and child.func.value.id == "current_guild_id":
                            has_set = True
                            break
            
            # Exclude help as we know it has it, and setting commands
            if not has_set and not node.name.startswith("settings_") and not node.name.startswith("tournament_"):
                missing.append((node.name, node.lineno))

visitor = CommandVisitor()
visitor.visit(tree)

print(f"Total commands missing current_guild_id.set: {len(missing)}")
for name, lineno in missing:
    print(f"- {name} (line {lineno})")
