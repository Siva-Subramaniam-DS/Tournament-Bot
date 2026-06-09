import os
import sys

# Add the current working directory (project root) to sys.path
sys.path.insert(0, os.getcwd())

def test_supabase_setup():
    print("--- Supabase Setup Test ---")
    
    # 1. Check environment variables
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    print(f"SUPABASE_URL defined: {bool(url)}")
    print(f"SUPABASE_KEY defined: {bool(key)}")
    
    # 2. Try importing components from main
    try:
        import main
        print("SUCCESS: main.py imported successfully!")
    except Exception as e:
        print(f"ERROR: Failed to import main.py: {e}")
        return False
        
    # 3. Verify client initialization
    if url and key:
        if main.supabase_client is not None:
            print("SUCCESS: Supabase client initialized successfully in main!")
        else:
            print("ERROR: Supabase client was not initialized despite variables being present!")
            return False
    else:
        print("WARNING: Supabase credentials not found in env, skipping live client test.")
        
    # 4. Check function signatures exist
    funcs = [
        "save_guild_config_to_supabase",
        "save_tournament_to_supabase",
        "delete_tournament_from_supabase",
        "sheetdb_post"
    ]
    for func in funcs:
        if hasattr(main, func):
            print(f"SUCCESS: Function '{func}' is defined in main.py")
        else:
            print(f"ERROR: Function '{func}' is missing in main.py!")
            return False
            
    print("SUCCESS: All checks passed successfully!")
    return True

if __name__ == "__main__":
    test_supabase_setup()
