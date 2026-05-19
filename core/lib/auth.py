import os
import hmac
from fastapi import Request, HTTPException

from core.services.db import get_supabase


def require_auth(request: Request):
    """Dual auth: accepts either X-API-Key (legacy) or Authorization: Bearer (JWT).
    Returns the user dict if JWT was used, None if API key was used.
    Raises 401 if neither is valid and API_SECRET_KEY is configured.
    """
    api_secret = os.getenv("API_SECRET_KEY")
    if not api_secret:
        return None

    api_key = request.headers.get("X-API-Key")
    if api_key and hmac.compare_digest(api_key, api_secret):
        return None

    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[len("Bearer "):]
        try:
            supabase = get_supabase()
            user_res = supabase.auth.get_user(token)
            if user_res and user_res.user:
                return user_res.user
        except Exception:
            pass

    raise HTTPException(status_code=401, detail="Unauthorized")


def get_current_user(request: Request):
    """JWT-only auth. Returns the authenticated user object.
    Use as FastAPI dependency: Depends(get_current_user).
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")

    token = auth_header[len("Bearer "):]
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    supabase = get_supabase()
    try:
        user_res = supabase.auth.get_user(token)
        user = user_res.user
        if not user:
            raise HTTPException(status_code=401, detail="Invalid token")
        return user
    except HTTPException:
        raise
    except Exception as e:
        print(f"Auth error: {e}")
        raise HTTPException(status_code=401, detail="Authentication failed")
