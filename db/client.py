"""
Supabase client — single instance used by all agents.
Import like: from db.client import db
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
        key = os.environ.get("SUPABASE_KEY")
        if not url or not key:
            raise RuntimeError(
                "SUPABASE_URL and SUPABASE_KEY must be set in your .env file"
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
