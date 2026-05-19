import os
import json
import secrets
from datetime import datetime, timezone, timedelta

from core.services.db import get_supabase


def register_user(user_id: str, email: str, owner_name: str = None):
    """Create a user_profiles entry after Google sign-in. Sets approval_status='pending'."""
    supabase = get_supabase()
    existing = supabase.table('user_profiles')\
        .select('user_id').eq('user_id', user_id).maybe_single().execute()
    if existing.data:
        return existing.data

    profile = {
        "user_id": user_id,
        "owner_name": owner_name or email.split('@')[0],
        "approval_status": "pending",
        "onboarding_completed": False
    }
    supabase.table('user_profiles').insert(profile).execute()
    return profile


def get_user_status(user_id: str) -> dict:
    """Returns approval status + onboarding progress."""
    supabase = get_supabase()
    profile = supabase.table('user_profiles')\
        .select('*').eq('user_id', user_id).maybe_single().execute()
    if not profile.data:
        return {"registered": False}

    p = profile.data
    telegram = supabase.table('user_telegram_links')\
        .select('chat_id').eq('user_id', user_id).maybe_single().execute()
    has_telegram = telegram.data is not None
    has_tokens = supabase.table('user_google_tokens')\
        .select('user_id').eq('user_id', user_id).maybe_single().execute()
    has_google = has_tokens.data is not None

    return {
        "registered": True,
        "approval_status": p["approval_status"],
        "onboarding_completed": p.get("onboarding_completed", False),
        "has_telegram": has_telegram,
        "has_google_tokens": has_google,
        "owner_name": p["owner_name"],
        "company_name": p.get("company_name"),
        "location": p.get("location"),
    }


def approve_user(admin_id: str, target_user_id: str) -> bool:
    """Admin approves a pending user."""
    supabase = get_supabase()
    admin_profile = supabase.table('user_profiles')\
        .select('approval_status').eq('user_id', admin_id).maybe_single().execute()
    if not admin_profile.data or admin_profile.data.get('approval_status') != 'approved':
        return False

    supabase.table('user_profiles')\
        .update({
            "approval_status": "approved",
            "approved_by": admin_id,
            "approved_at": datetime.now(timezone.utc).isoformat()
        }).eq('user_id', target_user_id).execute()
    return True


def get_pending_users(admin_id: str) -> list:
    """List all pending users (admin only)."""
    supabase = get_supabase()
    admin_profile = supabase.table('user_profiles')\
        .select('approval_status').eq('user_id', admin_id).maybe_single().execute()
    if not admin_profile.data or admin_profile.data.get('approval_status') != 'approved':
        return []

    result = supabase.table('user_profiles')\
        .select('user_id, owner_name, created_at')\
        .eq('approval_status', 'pending')\
        .order('created_at', desc=False)\
        .execute()
    return result.data or []


def get_persona(user_id: str) -> dict:
    """Get the user's persona configuration."""
    supabase = get_supabase()
    profile = supabase.table('user_profiles')\
        .select('*').eq('user_id', user_id).maybe_single().execute()
    if not profile.data:
        return {}
    p = profile.data
    return {
        "owner_name": p["owner_name"],
        "owner_full_name": p.get("owner_full_name"),
        "company_name": p.get("company_name"),
        "location": p.get("location"),
        "domains_config": p.get("domains_config", []),
    }


def set_persona(user_id: str, data: dict):
    """Update the user's persona configuration."""
    allowed = {"owner_name", "owner_full_name", "company_name", "location", "domains_config"}
    update = {k: v for k, v in data.items() if k in allowed}
    if not update:
        return
    update["updated_at"] = datetime.now(timezone.utc).isoformat()
    supabase = get_supabase()
    supabase.table('user_profiles').update(update).eq('user_id', user_id).execute()


def complete_onboarding(user_id: str):
    """Mark onboarding as completed."""
    supabase = get_supabase()
    supabase.table('user_profiles')\
        .update({"onboarding_completed": True, "updated_at": datetime.now(timezone.utc).isoformat()})\
        .eq('user_id', user_id).execute()


def generate_telegram_verification_code(user_id: str) -> str:
    """Generate a verification code for linking Telegram."""
    code = secrets.token_hex(4).upper()
    supabase = get_supabase()
    supabase.table('telegram_verification_codes').insert({
        "user_id": user_id,
        "code": code,
        "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    }).execute()
    return code


def verify_telegram_code(chat_id: int, code: str) -> str:
    """Verify a Telegram linking code. Returns the user_id if valid, None otherwise."""
    supabase = get_supabase()
    result = supabase.table('telegram_verification_codes')\
        .select('user_id, expires_at')\
        .eq('code', code)\
        .maybe_single().execute()
    if not result.data:
        return None
    expires = datetime.fromisoformat(result.data['expires_at'].replace('Z', '+00:00'))
    if datetime.now(timezone.utc) > expires:
        return None
    user_id = result.data['user_id']
    supabase.table('user_telegram_links').upsert({
        "user_id": user_id,
        "chat_id": chat_id,
        "verified_at": datetime.now(timezone.utc).isoformat()
    }).execute()
    supabase.table('telegram_verification_codes')\
        .delete().eq('user_id', user_id).execute()
    return user_id
