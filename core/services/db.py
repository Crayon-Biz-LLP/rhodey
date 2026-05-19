import os
import contextvars
from supabase import create_client, Client
from core.lib.audit_logger import audit_log_sync

_supabase: Client = None
_current_user_id: contextvars.ContextVar = contextvars.ContextVar('current_user_id', default=None)

SYSTEM_TABLES = {'core_config', 'audit_logs', 'failed_queue', 'model_registry', 'processed_updates', 'canonical_pages'}


def set_current_user(user_id: str):
    """Set the current user_id for the request context. All subsequent user_query() calls
    will automatically filter by this user_id."""
    _current_user_id.set(user_id)


def get_current_user_id() -> str:
    """Get the current user_id from request context."""
    return _current_user_id.get()


def get_supabase() -> Client:
    global _supabase
    if _supabase is None:
        _supabase = create_client(
            os.getenv("SUPABASE_URL"),
            os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        )
    return _supabase


def user_query(table_name: str, user_id: str = None):
    """Returns a supabase table query builder with user_id pre-filtered.
    Falls back to _current_user_id context var if no user_id given.
    Skips user_id for system tables (core_config, audit_logs, etc.).
    """
    uid = user_id or get_current_user_id()
    query = get_supabase().table(table_name)
    if table_name not in SYSTEM_TABLES and uid:
        query = query.eq('user_id', uid)
    return query


def user_insert(table_name: str, data: dict, user_id: str = None):
    """Insert a record with user_id automatically injected.
    Skips user_id for system tables.
    """
    uid = user_id or get_current_user_id()
    if table_name not in SYSTEM_TABLES and uid:
        data = {**data, "user_id": uid}
    return get_supabase().table(table_name).insert(data)


def get_embedding(text: str, model: str = "gemini-embedding-2-preview", dimension: int = 768) -> list:
    from google import genai
    gemini = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    try:
        result = gemini.models.embed_content(
            model=model,
            contents=text,
            config={'output_dimensionality': dimension}
        )
        return result.embeddings[0].values
    except Exception as e:
        audit_log_sync("db", "ERROR", f"Embedding error: {e}")
        return [0] * dimension


def fetch_active_projects() -> list:
    supabase = get_supabase()
    try:
        res = supabase.table('projects').select('id, name, org_tag').eq('status', 'active').execute()
        return res.data or []
    except Exception as e:
        audit_log_sync("db", "WARNING", f"Failed to fetch projects: {e}")
        return []


def zombie_recovery():
    from datetime import datetime, timezone, timedelta
    supabase = get_supabase()
    try:
        ten_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        supabase.table('raw_dumps') \
            .update({"status": "pending"}) \
            .eq('status', 'processing') \
            .lt('created_at', ten_mins_ago) \
            .execute()
    except Exception as e:
        audit_log_sync("db", "WARNING", f"Zombie recovery failed: {e}")


def versioned_update(table_name: str, record_id: int, update_data: dict, user_id=None, change_source=None, change_reason=None):
    supabase = get_supabase()
    try:
        current = supabase.table(table_name).select('*').eq('id', record_id).execute()
        if not current.data:
            audit_log_sync("db", "WARNING", f"Record {record_id} not found in {table_name}")
            return False

        old_record = current.data[0]
        new_record = {
            **{k: v for k, v in old_record.items()
               if k not in ['id', 'created_at', 'version', 'is_current', 'supersedes_id', 'updated_at']},
            **{k: v for k, v in update_data.items() if v is not None},
            **{k: v for k, v in update_data.items() if v is None},
            'is_current': True
        }

        old_version = old_record.get('version', 0) or 0
        new_record['version'] = old_version + 1
        new_record['supersedes_id'] = record_id

        result = supabase.table(table_name).insert(new_record).execute()
        supabase.table(table_name).update({"is_current": False}).eq('id', record_id).execute()

        if change_source or change_reason:
            audit_log_sync("db", "INFO",
                          f"Versioned update: {table_name}:{record_id} v{new_record['version']}",
                          {"source": change_source, "reason": change_reason, "user_id": user_id})

        return bool(result.data)

    except Exception as e:
        audit_log_sync("db", "WARNING", f"Versioned update failed for {table_name}:{record_id}, falling back: {e}")
        fallback_data = {**update_data, 'is_current': True}
        supabase.table(table_name).update(fallback_data).eq('id', record_id).execute()
        return True
