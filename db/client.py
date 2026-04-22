"""
Supabase client — single instance used by all agents.
Import like: from db.client import db

Key priority:
  SUPABASE_SERVICE_KEY → service_role key (bypasses RLS, backend only)
  SUPABASE_KEY         → anon key fallback (has RLS restrictions)

NEVER expose SUPABASE_SERVICE_KEY to the frontend.
Get it from: Supabase dashboard → Project Settings → API → service_role key.
"""

import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()

_client: Client | None = None


def get_client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        # Prefer service_role key (bypasses RLS for backend writes)
        key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_SERVICE_KEY (or SUPABASE_KEY) "
                "must be set in your .env file"
            )
        if key == os.environ.get("SUPABASE_KEY") and not os.environ.get("SUPABASE_SERVICE_KEY"):
            print(
                "  [db] WARNING: Using anon key. RLS policies will restrict writes. "
                "Set SUPABASE_SERVICE_KEY in .env for full backend access."
            )
        _client = create_client(url, key)
    return _client


# Convenience alias
db = get_client


if __name__ == "__main__":
    # Quick connection test — run: python db/client.py
    client = get_client()
    result = client.table("listings").select("id").limit(1).execute()
    print("Supabase connection OK. Rows in listings table:", len(result.data))
