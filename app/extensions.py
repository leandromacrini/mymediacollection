try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

if load_dotenv:
    # Ensure local .env is loaded before DB settings are read.
    load_dotenv()

from core.db_core import MediaDB

db = MediaDB()
