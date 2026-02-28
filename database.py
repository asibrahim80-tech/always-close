from supabase import create_client
from config import SUPABASE_URL, SUPABASE_KEY


# ==========================
# Create Supabase Client
# ==========================

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
