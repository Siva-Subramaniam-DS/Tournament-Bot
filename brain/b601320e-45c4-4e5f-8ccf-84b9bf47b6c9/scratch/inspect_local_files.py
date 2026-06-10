import json
import os

guild_id = "1303670721796640799"

if os.path.exists("guild_configs.json"):
    with open("guild_configs.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        print("=== Local Guild Config ===")
        if guild_id in data:
            print(json.dumps(data[guild_id], indent=2))
        else:
            print("Not found in guild_configs.json")
else:
    print("guild_configs.json does not exist")

if os.path.exists("tournaments.json"):
    with open("tournaments.json", "r", encoding="utf-8") as f:
        data = json.load(f)
        print("\n=== Local Tournaments ===")
        if guild_id in data:
            print(json.dumps(data[guild_id], indent=2))
        else:
            print("Not found in tournaments.json")
else:
    print("tournaments.json does not exist")
