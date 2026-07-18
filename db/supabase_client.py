"""
/db/supabase_client.py
======================
Shared Supabase client — import this singleton from any agent that needs DB access.

Usage:
    from db.supabase_client import supabase
    response = supabase.table("processed_signals").insert([...]).execute()

Requires SUPABASE_URL and SUPABASE_SERVICE_KEY in the .env file (or environment).
python-dotenv is used to load .env automatically so you don't need to export vars
manually before running scripts.
"""

import os
import pathlib

from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env from repo root (two levels up from this file: db/ → project root)
_env_path = pathlib.Path(__file__).parent.parent / ".env"
load_dotenv(_env_path)

supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_SERVICE_KEY")

if not supabase_url or not supabase_key:
    raise EnvironmentError(
        "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in .env "
        f"(looked for: {_env_path})"
    )

supabase: Client = create_client(supabase_url, supabase_key)
