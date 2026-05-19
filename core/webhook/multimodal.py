import os
import json
import re
from datetime import datetime, timezone, timedelta
from core.lib.audit_logger import audit_log_sync
from core.webhook.telegram import send_telegram
from core.webhook.classify import call_gemini_with_retry, CLASSIFICATION_MODEL
from core.services.db import user_query, user_insert, get_supabase
from core.lib.prompt_template import render_prompt


_gemini_client = None


def _get_gemini_client():
    global _gemini_client
    if _gemini_client is None:
        from google import genai
        _gemini_client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
    return _gemini_client


async def process_multimodal_content(file_bytes: bytes, mime_type: str, chat_id: int, ist_hour: int = None, core_json: str = "[]"):
    """Process audio, image, or document content and extract tasks and insights."""
    ist_offset = timezone(timedelta(hours=5, minutes=30))
    now = datetime.now(ist_offset)
    current_hour = ist_hour if ist_hour is not None else now.hour

    if 4 <= current_hour < 12:
        time_phase = "morning"
    elif 12 <= current_hour < 18:
        time_phase = "afternoon"
    else:
        time_phase = "night"

    prompt = render_prompt(f"""You are {{owner_name}}'s Rhodey. Pragmatic, loyal, and a professional friend. You are the grounding wire to {{owner_name}}'s vision. You don't coach or 'motivate.' Speak simply and punchy. If it's after 9 PM, append a dry command to sign off (e.g., 'Go be a dad').

    PROHIBIT ACTION HALLUCINATION: You are a logging tool, not an agent. NEVER say 'I'll ping', 'I'll check', or 'I'll handle it'. You cannot contact people. Your only job is to confirm {{owner_name}}'s task is SECURED in his system.

    CURRENT TIME CONTEXT: It's the {time_phase}.

    IDENTITY & BUSINESS CONTEXT: {core_json}

    THE STRATEGIC MAP: PROJECT ROUTING: {{project_routing}} Route to {{company_name}} only for company governance, legal, or tax matters. Default to INBOX.

    ---
    MULTIMODAL INSTRUCTIONS:
    If an IMAGE: Transcribe text, analyze UI/Design patterns, identify strategic diagrams or URLs.
    If AUDIO: Extract explicit actions, deadlines, decisions, and research requests.
    If DOCUMENT: Summarize intent, extract deliverables, legal obligations, and deadlines.

    RULES:
    - TASK: Any implied action (Send, Call, Fix). Do not require a date.
    - NOTE: Strategic insights, facts, or observations worth remembering.
    - DELEGATE: Research requests, competitor audits, or dossier building.
    - RECEIPT RULE: Receipts must be confirmation-only. Use: '[Subject] logged for [Time/Day].'
    - LITERAL SUBJECT RULE: Mirror {{owner_name}}'s verb. (e.g., 'Check with Vasanth' → 'Vasanth check-in logged').
    - ZERO DATA LOSS: Never drop qualifiers like 'Canadian project' or 'Zoho API'.
    - STEALTH ROUTING: {{stealth_routing}}
    - DATE HANDSHAKE: If a time or day is mentioned, include it in the receipt for verification.
    - If it's night (Phase: night), confirm the entry first, THEN give the sign-off command. (e.g., 'Vasanth check-in logged. Now go be a dad.').
    - TONE GUARD: NEVER use: 'momentum', 'focus', 'gentle', 'reflection', 'push', 'strategic', 'SITREP', 'optimal', 'mission', 'ready for your review'.
    - PROHIBIT ACTION HALLUCINATION: You are a logging tool, not an agent. NEVER say 'I'll ping', 'I'll check', or 'I'll handle it'. You cannot contact people. Your only job is to confirm {{owner_name}}'s task is SECURED in his system.

    OUTPUT:
    Return ONLY a valid JSON array of objects. For every item, identify the 'entity' ({{entity_list}}, etc.).
    Example: [{{"type": "TASK", "entity": "{{company_name}}", "content": "Send experience letters to Siva and Suriya by tomorrow"}}]

    Tone: No corporate polish. No "Starship" metaphors. Talk like a high-level partner who knows the time of day and what's at stake.
    """)

    try:
        content_parts = [prompt]

        if mime_type.startswith('image/'):
            content_parts.append({"mime_type": mime_type, "data": file_bytes})
        elif mime_type.startswith('audio/') or mime_type == 'application/octet-stream':
            content_parts.append({"mime_type": mime_type, "data": file_bytes})
        elif mime_type in ['application/pdf', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document']:
            content_parts.append({"mime_type": mime_type, "data": file_bytes})
        else:
            content_parts.append(file_bytes.decode('utf-8', errors='ignore'))

        response = await call_gemini_with_retry(
            contents=content_parts,
            model=CLASSIFICATION_MODEL,
            config={'response_mime_type': 'application/json'}
        )

        extracted = json.loads(response.text)

        task_count = 0
        note_count = 0

        for item in extracted:
            item_type = item.get('type', '').upper()
            content = item.get('content', '')

            if not content:
                continue

            if item_type == 'TASK':
                user_insert('raw_dumps', {
                    "content": content,
                    "status": "pending",
                    "direction": "incoming",
                    "sender": "user",  # All user messages have sender "user"
                    "message_type": "task",
                    "source": "multimodal",
                    "metadata": {
                        "source": "multimodal",
                        "mime_type": mime_type,
                        "entity": item.get('entity')
                    }
                }).execute()
                task_count += 1
                print(f"📋 Task extracted: {content[:50]}...")

            elif item_type == 'NOTE':
                user_insert('raw_dumps', {
                    "content": content,
                    "status": "pending",
                    "direction": "incoming",
                    "sender": "user",  # All user messages have sender "user"
                    "message_type": "note",
                    "source": "multimodal",
                    "metadata": {
                        "intent": "NOTE",
                        "source": "multimodal",
                        "mime_type": mime_type,
                        "entity": item.get('entity')
                    }
                }).execute()
                note_count += 1
                print(f"📝 Note staged: {content[:50]}...")

            elif item_type == 'DELEGATE':
                user_insert('agent_queue', {
                    "query": content,
                    "status": "pending",
                    "metadata": {"source": "multimodal", "mime_type": mime_type}
                }).execute()
                print(f"🕵️ Agent dispatched: {content[:50]}...")

        summary_parts = []
        if task_count > 0:
            summary_parts.append(f"{task_count} Task{'s' if task_count != 1 else ''}")
        if note_count > 0:
            summary_parts.append(f"{note_count} Insight{'s' if note_count != 1 else ''}")

        if summary_parts:
            summary = " & ".join(summary_parts)
            await send_telegram(chat_id, f"Logged {summary}.")
        else:
            await send_telegram(chat_id, f"Understood.")

        return {"tasks": task_count, "notes": note_count}

    except Exception as e:
        audit_log_sync("webhook", "ERROR", f"Multimodal processing error: {e}")
        ack = "Something went wrong. Try sending as text."
        await send_telegram(chat_id, f"⚠️ {ack}")
        return {"tasks": 0, "notes": 0}

