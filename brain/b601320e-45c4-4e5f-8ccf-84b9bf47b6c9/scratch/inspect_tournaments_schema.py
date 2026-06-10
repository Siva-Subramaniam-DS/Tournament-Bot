import os
import requests
from dotenv import load_dotenv

load_dotenv()

def get_db_schema():
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        print("Missing SUPABASE_URL or SUPABASE_KEY")
        return
        
    rest_url = f"{url}/rest/v1/"
    headers = {
        "apikey": key,
        "Authorization": f"Bearer {key}"
    }
    
    try:
        resp = requests.get(rest_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            schema = resp.json()
            definitions = schema.get("definitions", {})
            print("=== DB SCHEMA TABLES ===")
            for table_name, val in definitions.items():
                print(f"\nTable: {table_name}")
                properties = val.get("properties", {})
                for col_name, col_info in properties.items():
                    print(f"  {col_name}: {col_info.get('type')} (format: {col_info.get('format')})")
        else:
            print(f"Failed to fetch schema ({resp.status_code}): {resp.text}")
    except Exception as e:
        print(f"Error fetching schema: {e}")

if __name__ == "__main__":
    get_db_schema()
