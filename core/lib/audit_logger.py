"""
Audit Logger - Replaces print() with permanent audit trail.
Writes to Supabase audit_logs table for observability.
Lazy-init: the Supabase client is NOT created at import time.
"""
import os
import json
import traceback
from datetime import datetime, timezone

_supabase = None


def _get_supabase():
    global _supabase
    if _supabase is None:
        from supabase import create_client
        from dotenv import load_dotenv
        dotenv_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
        load_dotenv(dotenv_path)
        _supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        )
    return _supabase


async def audit_log(service: str, level: str, message: str, metadata: dict = None):
    try:
        log_data = {
            "service": service,
            "level": level,
            "message": message[:500] if message else "(empty)",
            "metadata": json.dumps(metadata or {})
        }
        _get_supabase().table('audit_logs').insert(log_data).execute()
    except Exception as e:
        print(f"⚠️ AUDIT LOG FAILURE: {e} | Original: [{service}] {level}: {message}")


def audit_log_sync(service: str, level: str, message: str, metadata: dict = None):
    try:
        log_data = {
            "service": service,
            "level": level,
            "message": message[:500] if message else "(empty)",
            "metadata": json.dumps(metadata or {})
        }
        _get_supabase().table('audit_logs').insert(log_data).execute()
    except Exception as e:
        print(f"⚠️ AUDIT LOG FAILURE: {e} | Original: [{service}] {level}: {message}")


def format_error(e: Exception) -> dict:
    """Format an exception into metadata dict."""
    return {
        "error_type": type(e).__name__,
        "error_message": str(e)[:200],
        "traceback": traceback.format_exc()[:500] if hasattr(traceback, 'format_exc') else None
    }


# Convenience wrappers
def info(service: str, message: str, metadata: dict = None):
    """Log INFO level."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(audit_log(service, 'INFO', message, metadata))
        else:
            audit_log_sync(service, 'INFO', message, metadata)
    except:
        audit_log_sync(service, 'INFO', message, metadata)


def warning(service: str, message: str, metadata: dict = None):
    """Log WARNING level."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(audit_log(service, 'WARNING', message, metadata))
        else:
            audit_log_sync(service, 'WARNING', message, metadata)
    except:
        audit_log_sync(service, 'WARNING', message, metadata)


def error(service: str, message: str, metadata: dict = None):
    """Log ERROR level."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(audit_log(service, 'ERROR', message, metadata))
        else:
            audit_log_sync(service, 'ERROR', message, metadata)
    except:
        audit_log_sync(service, 'ERROR', message, metadata)


def critical(service: str, message: str, metadata: dict = None):
    """Log CRITICAL level."""
    import asyncio
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            asyncio.ensure_future(audit_log(service, 'CRITICAL', message, metadata))
        else:
            audit_log_sync(service, 'CRITICAL', message, metadata)
    except:
        audit_log_sync(service, 'CRITICAL', message, metadata)
