import os
import hmac
import hashlib
import time
from datetime import datetime, timedelta
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from core.webhook import process_webhook, send_draft_reply, process_email_pending_decision
from core.pulse import (
    process_pulse,
    get_tasks_service,
    sync_to_google,
    delete_calendar_event,
    versioned_update,
    write_outcome_memory,
    get_outlook_calendar_events,
    get_outlook_calendar_events_range,
    get_google_creds,
    format_rfc3339,
)
from core.services.db import get_supabase, set_current_user, user_query, user_insert
from core.services.onboarding import (
    register_user, get_user_status, approve_user, get_pending_users,
    get_persona, set_persona, complete_onboarding,
    generate_telegram_verification_code, verify_telegram_code,
)
from core.lib.auth import require_auth, get_current_user
from core.lib.domain_utils import DEFAULT_DOMAINS

app = FastAPI(title="Rhodey")


# ==================== AUTH & ONBOARDING ====================

@app.post("/api/auth/register")
async def auth_register_route(request: Request):
    """Register after Google OAuth. Creates a pending user profile."""
    user = get_current_user(request)
    set_current_user(user.id)
    body = await request.json()
    profile = register_user(user.id, user.email, body.get("owner_name"))
    return {"registered": True, "approval_status": profile.get("approval_status", "pending")}


@app.get("/api/auth/status")
async def auth_status_route(request: Request):
    """Get current user's registration/approval/onboarding status."""
    user = get_current_user(request)
    set_current_user(user.id)
    return get_user_status(user.id)


@app.post("/api/admin/users/approve")
async def admin_approve_user_route(request: Request):
    """Admin approves a pending user."""
    user = get_current_user(request)
    set_current_user(user.id)
    body = await request.json()
    target = body.get("user_id")
    if not target:
        raise HTTPException(status_code=400, detail="user_id required")
    ok = approve_user(user.id, target)
    if not ok:
        raise HTTPException(status_code=403, detail="Not authorized or user not found")
    return {"success": True}


@app.get("/api/admin/users/pending")
async def admin_pending_users_route(request: Request):
    """List pending users (admin only)."""
    user = get_current_user(request)
    set_current_user(user.id)
    return {"users": get_pending_users(user.id)}


@app.get("/api/onboarding/persona")
async def get_persona_route(request: Request):
    """Get current user's persona configuration."""
    user = get_current_user(request)
    set_current_user(user.id)
    return get_persona(user.id)


@app.post("/api/onboarding/persona")
async def set_persona_route(request: Request):
    """Update persona (name, company, location, domains)."""
    user = get_current_user(request)
    set_current_user(user.id)
    body = await request.json()
    set_persona(user.id, body)
    return {"success": True}


@app.post("/api/onboarding/complete")
async def complete_onboarding_route(request: Request):
    """Mark onboarding wizard as complete."""
    user = get_current_user(request)
    set_current_user(user.id)
    complete_onboarding(user.id)
    return {"success": True}


@app.post("/api/onboarding/telegram/link")
async def telegram_link_route(request: Request):
    """Generate a verification code to link Telegram."""
    user = get_current_user(request)
    set_current_user(user.id)
    code = generate_telegram_verification_code(user.id)
    return {"code": code, "expires_in_minutes": 10}


@app.get("/api/onboarding/domains")
async def get_domains_route(request: Request):
    """Get the user's domain configuration (or defaults if not set)."""
    user = get_current_user(request)
    set_current_user(user.id)
    persona = get_persona(user.id)
    config = persona.get("domains_config") or DEFAULT_DOMAINS
    return {"domains_config": config, "defaults": DEFAULT_DOMAINS}


@app.post("/api/onboarding/domains")
async def save_domains_route(request: Request):
    """Save the user's custom domain configuration."""
    user = get_current_user(request)
    set_current_user(user.id)
    body = await request.json()
    domains = body.get("domains_config", [])
    set_persona(user.id, {"domains_config": domains})
    return {"success": True}


# CORS setup for future dashboard scalability
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def health_check():
    return {"status": "Rhodey API is running on Python 🐍"}

# --- TELEGRAM INTAKE (Routes to webhook.py) ---
@app.post("/api/webhook")
async def webhook_route(request: Request):
    update = await request.json()
    try:
        await process_webhook(update)
        return {"success": True}
    except Exception as e:
        print(f"Webhook route error: {e}")
        raise HTTPException(status_code=500, detail="Internal processing error")

def verify_hmac(payload: bytes, signature: str, secret: str) -> bool:
    expected = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)

# --- THE PULSE ENGINE (Routes to pulse.py) ---
@app.post("/api/pulse")
async def pulse_route_post(request: Request):
    # HMAC-SHA256 verification for Pulse trigger requests
    raw_body = await request.body()
    sig_header = request.headers.get('X-Rhodey-Signature', '')
    
    pulse_secret = os.getenv("PULSE_SECRET")
    if not verify_hmac(raw_body, sig_header, pulse_secret):
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    
    secret = request.headers.get("x-pulse-secret")
    body = await request.json() if request.headers.get("content-type") == "application/json" else {}
    user_id = body.get("user_id") or request.query_params.get("user_id")
    
    result = await process_pulse(auth_secret=secret, user_id=user_id)
    
    if result.get("error"):
        raise HTTPException(status_code=result.get("status", 500), detail=result["error"])
        
    return {"success": True, "briefing": result.get("briefing")}

# --- SEND DRAFT REPLY (Routes to webhook.py) ---
@app.post("/api/send-draft")
async def send_draft_route(request: Request):
    user = require_auth(request)
    if user:
        set_current_user(user.id)
    body = await request.json()
    draft_id = body.get("draft_id")
    if not draft_id:
        raise HTTPException(status_code=400, detail="draft_id required")
    success, error = await send_draft_reply(draft_id)
    return {"success": success, "error": error}

# --- SEND MESSAGE VIA WEB UI (Mirrors Telegram exactly) ---
@app.post("/api/send-message")
async def send_message_route(request: Request):
    user = require_auth(request)
    if user:
        set_current_user(user.id)
    try:
        body = await request.json()
        message_text = body.get("message")
        if not message_text:
            raise HTTPException(status_code=400, detail="message required")
        
        # Validate Telegram credentials
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        
        if not telegram_bot_token or not telegram_chat_id:
            raise HTTPException(status_code=500, detail="Telegram credentials not configured")
        
        # Create a fake Telegram update object (mirrors what Telegram sends)
        # Prefix update_id with "web_" to identify web UI messages
        fake_update = {
            "update_id": f"web_{int(time.time() * 1000)}",
            "message": {
                "chat": {"id": int(telegram_chat_id)},
                "text": message_text,
                "date": int(time.time())
            }
        }
        
        # Process exactly like Telegram webhook
        print(f"🧪 Processing web message as Telegram update: {fake_update}")
        result = await process_webhook(fake_update)
        print(f"🧪 Webhook result: {result}")
        
        return {"success": True, "message": "Message processed"}
    
    except Exception as e:
        print(f"Send message error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- GET MESSAGE HISTORY ---
@app.get("/api/messages")
async def get_messages_route(request: Request, limit: int = 50, offset: int = 0):
    user = require_auth(request)
    if user:
        set_current_user(user.id)
    try:
        result = user_query('raw_dumps')\
            .select('id, content, created_at, direction, sender, message_type, status, metadata, source')\
            .order('created_at', desc=True)\
            .limit(limit)\
            .offset(offset)\
            .execute()
        return {"messages": result.data or []}
    except Exception as e:
        print(f"Get messages error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- CALENDAR EVENTS (Fetches from Google + Outlook) ---
@app.get("/api/calendar-events")
async def get_calendar_events(request: Request, date: str = None, start: str = None, end: str = None):
    user = require_auth(request)
    if user:
        set_current_user(user.id)
    try:
        from googleapiclient.discovery import build

        if start and end:
            start_dt = datetime.fromisoformat(start).replace(hour=0, minute=0, second=0)
            end_dt = datetime.fromisoformat(end).replace(hour=23, minute=59, second=59)
            rfc_start = format_rfc3339(start_dt)
            rfc_end = format_rfc3339(end_dt)
        elif date == "today" or not date:
            today = datetime.now()
            start_dt = today.replace(hour=0, minute=0, second=0)
            end_dt = start_dt.replace(hour=23, minute=59, second=59)
            rfc_start = format_rfc3339(start_dt)
            rfc_end = format_rfc3339(end_dt)
        else:
            target = datetime.fromisoformat(date)
            start_dt = target.replace(hour=0, minute=0, second=0)
            end_dt = start_dt.replace(hour=23, minute=59, second=59)
            rfc_start = format_rfc3339(start_dt)
            rfc_end = format_rfc3339(end_dt)

        simplified = []

        service = build('calendar', 'v3', credentials=get_google_creds())
        events_res = service.events().list(
            calendarId='primary',
            timeMin=rfc_start,
            timeMax=rfc_end,
            singleEvents=True,
            orderBy='startTime',
            maxResults=50
        ).execute()
        for event in events_res.get('items', []):
            simplified.append({
                'id': event.get('id'),
                'summary': event.get('summary', 'No Title'),
                'start': event.get('start', {}),
                'end': event.get('end', {}),
                'description': event.get('description', ''),
                'source': 'google',
            })

        try:
            outlook_events = get_outlook_calendar_events_range(start_dt, end_dt) \
                if start and end else get_outlook_calendar_events(start_dt)
            for e in outlook_events:
                simplified.append({
                    'id': e.get('id'),
                    'summary': e.get('title'),
                    'start': {'dateTime': e['time']},
                    'source': 'outlook',
                })
        except Exception as ol_err:
            print(f"Outlook calendar events error: {ol_err}")

        return {"events": simplified}
    except Exception as e:
        print(f"Calendar events error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- UPDATE TASK STATUS (Mark Done) ---
@app.patch("/api/tasks/{task_id}/status")
async def update_task_status(request: Request, task_id: int):
    user = require_auth(request)
    if user:
        set_current_user(user.id)
    try:
        body = await request.json()
        new_status = body.get('status', 'done')

        task_res = user_query('tasks').select('*').eq('id', task_id).eq('is_current', True).single().execute()
        if not task_res.data:
            raise HTTPException(status_code=404, detail="Task not found")

        task = task_res.data
        current_status = task.get('status')
        if current_status in ['done', 'cancelled']:
            return {"success": True, "task": task, "message": f"Task already {current_status}"}

        g_id = task.get('google_task_id')
        e_id = task.get('google_event_id')
        task_title = task.get('title', 'Untitled Task')

        if e_id and new_status in ['done', 'cancelled']:
            try:
                delete_calendar_event(e_id)
            except Exception as e:
                print(f"Calendar event delete failed (non-critical): {e}")

        if g_id and new_status in ['done', 'cancelled']:
            try:
                tasks_service = get_tasks_service()
                sync_to_google(tasks_service, title=task_title, task_id=g_id, status=new_status)
            except Exception as e:
                print(f"Google Tasks sync failed (non-critical): {e}")

        update_data = {'status': new_status}
        if new_status == 'done':
            update_data['completed_at'] = datetime.now().isoformat()

        versioned_update(
            table_name='tasks',
            record_id=task_id,
            update_data=update_data,
            change_source='web_done',
            change_reason=f"Status: {new_status}"
        )

        if new_status == 'done':
            proj_name = None
            proj_id = task.get('project_id')
            if proj_id:
                proj_lookup = user_query('projects').select('name').eq('id', proj_id).maybe_single().execute()
                proj_name = proj_lookup.data['name'] if proj_lookup.data else None
            await write_outcome_memory(task_title, proj_name)

        new_task_res = user_query('tasks').select('*').eq('supersedes_id', task_id).eq('is_current', True).single().execute()
        new_task = new_task_res.data if new_task_res.data else task

        return {"success": True, "task": new_task}

    except HTTPException:
        raise
    except Exception as e:
        print(f"Update task status error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# --- EMAIL PENDING TASK DECISIONS (approve/reject from frontend) ---
@app.post("/api/email-action")
async def email_action_route(request: Request):
    """Approve or reject email pending task via API (called from frontend)."""
    user = require_auth(request)
    if user:
        set_current_user(user.id)
    try:
        body = await request.json()
        pending_id = body.get('id') or body.get('shortcode')
        action = body.get('action', '')  # 'approve'/'reject' or 'yes'/'no'

        if not pending_id or not action:
            raise HTTPException(status_code=400, detail="id and action required")

        # Normalize action: 'yes'/'no' → 'approve'/'reject'
        if action == 'yes':
            action = 'approve'
        elif action == 'no':
            action = 'reject'

        result = await process_email_pending_decision(int(pending_id), action)

        if result['success']:
            return {"success": True, "message": result['message'], "action": result['action']}
        else:
            return {"success": False, "message": result['message'], "action": result['action']}

    except Exception as e:
        print(f"Email action error: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")