import os
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
client = create_client(url, key)

print("Checking if we can run SQL via RPC...")
sql = """
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Captains_Sheet_Link" text;
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Thumbnail_Channel_ID" text;
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Schedule_Channel_ID" text;
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Challonge_Logs_Channel_ID" text;
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Transcript_Logs_Channel_ID" text;
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Bot_Logs_Channel_ID" text;
ALTER TABLE "Tournaments" ADD COLUMN IF NOT EXISTS "Participant_Channel_ID" text;
"""

try:
    # Try calling a generic execute/rpc if it exists
    resp = client.rpc("exec_sql", {"sql": sql}).execute()
    print("SUCCESS via exec_sql RPC!")
    print(resp.data)
except Exception as e:
    print(f"Failed RPC exec_sql: {e}")
