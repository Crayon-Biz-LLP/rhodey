import asyncio
import json
import os
import httpx
from datetime import datetime, timezone

from core.services.db import user_query, user_insert, get_supabase, get_embedding, get_current_user_id
from core.services.llm import call_gemini_with_retry
from core.lib.prompt_template import render_prompt
from core.lib.domain_utils import DEFAULT_DOMAINS

SKIP_ORG_TAGS = {None, 'INBOX'}
MIN_FRAGMENT_THRESHOLD = 5


def _get_domain_config():
    user_id = get_current_user_id()
    if not user_id:
        return DEFAULT_DOMAINS
    profile = get_supabase().table('user_profiles').select('domains_config').eq('user_id', user_id).maybe_single().execute()
    if profile.data and profile.data.get('domains_config'):
        return profile.data['domains_config']
    return DEFAULT_DOMAINS


def _get_parent_org_tags():
    config = _get_domain_config()
    return {d['tag'] for d in config}


def _get_org_tag_context():
    config = _get_domain_config()
    return {d['tag']: d.get('description', d['tag']) for d in config}


def filter_fragments_by_project(results, project_name):
    """Filter RPC results to only include fragments matching this project."""
    if not results:
        return []
    project_kw = project_name.lower()
    filtered = []
    for r in results:
        meta = r.get('metadata') or {}
        entity = (meta.get('entity') or '').lower() if isinstance(meta, dict) else ''
        content = (r.get('content') or r.get('title') or '').lower()
        if project_kw in entity or project_kw in content:
            filtered.append(r)
    return filtered


async def run_batch_sweep():
    try:
        active_res = user_query('projects') \
            .select('id, name, org_tag') \
            .eq('is_active', True) \
            .eq('status', 'active') \
            .execute()
        entities = []
        for p in active_res.data:
            org_tag = p.get('org_tag')
            if org_tag not in SKIP_ORG_TAGS:
                entities.append((p['id'], p.get('name') or p.get('title', ''), org_tag))

        batch_payload = []

        print(f"Gathering fragments for {len(entities)} entities...")
        for project_id, entity_name, org_tag in entities:
            try:
                all_fragments = []
                seen_hashes = set()

                def add_fragment(prefix: str, text: str):
                    normalized = text.strip().lower()
                    h = hash(normalized)
                    if h not in seen_hashes and normalized:
                        seen_hashes.add(h)
                        all_fragments.append(f"[{prefix}] {text}")

                entity_embedding = get_embedding(entity_name)

                if entity_embedding:
                    mem = get_supabase().rpc('match_memories', {
                        'query_embedding': entity_embedding,
                        'match_threshold': 0.5,
                        'match_count': 20
                    }).execute()
                    if mem.data:
                        for f in filter_fragments_by_project(mem.data, entity_name):
                            add_fragment("MEMORY", f['content'])

                tasks = user_query('tasks').select('title, status') \
                    .eq('project_id', project_id).execute()
                if tasks.data:
                    for t in tasks.data:
                        add_fragment(f"TASK/{t['status'].upper()}", t['title'])

                if entity_embedding:
                    logs = get_supabase().rpc('match_logs', {
                        'query_embedding': entity_embedding,
                        'match_threshold': 0.5,
                        'match_count': 20
                    }).execute()
                    if logs.data:
                        for f in filter_fragments_by_project(logs.data, entity_name):
                            add_fragment("LOG", f['content'])

                if entity_embedding:
                    resources = get_supabase().rpc('match_resources', {
                        'query_embedding': entity_embedding,
                        'match_threshold': 0.5,
                        'match_count': 10
                    }).execute()
                    if resources.data:
                        for r in filter_fragments_by_project(resources.data, entity_name):
                            add_fragment("RESOURCE", f"{r['title']} — {r.get('summary', '')}")

                if entity_embedding:
                    dumps = get_supabase().rpc('match_raw_dumps', {
                        'query_embedding': entity_embedding,
                        'match_threshold': 0.5,
                        'match_count': 30
                    }).execute()
                    if dumps.data:
                        for d in filter_fragments_by_project(dumps.data, entity_name):
                            add_fragment("DUMP", d['content'])

                people = user_query('people').select('name, role, strategic_weight') \
                    .ilike('name', f'%{entity_name}%').execute()
                if people.data:
                    for p in people.data:
                        add_fragment("PERSON", f"{p.get('name', 'Unknown')} — {p.get('role', 'Unknown role')}")

                if org_tag in _get_parent_org_tags():
                    child_res = user_query('projects') \
                        .select('id, name') \
                        .eq('parent_project_id', project_id) \
                        .eq('status', 'active') \
                        .execute()
                    for child in child_res.data or []:
                        child_tasks = user_query('tasks').select('title, status') \
                            .eq('project_id', child['id']).execute()
                        for t in child_tasks.data or []:
                            add_fragment(f"CHILD_TASK/{t['status'].upper()}", f"[{child['name']}] {t['title']}")

            except Exception as e:
                print(f"Skipping {entity_name} — failed to fetch fragments: {e}")
                continue

            is_parent = org_tag in _get_parent_org_tags() and entity_name.lower() == org_tag.lower()

            existing = get_supabase().table('canonical_pages') \
                .select('id, content') \
                .eq('project_id', project_id) \
                .eq('is_current', True) \
                .limit(1).execute()
            existing_content = existing.data[0]["content"] if existing.data else None
            existing_id = existing.data[0]["id"] if existing.data else None

            if len(all_fragments) >= MIN_FRAGMENT_THRESHOLD or is_parent:
                batch_payload.append({
                    "entity": entity_name,
                    "project_id": project_id,
                    "org_tag": org_tag,
                    "is_parent": is_parent,
                    "existing_page": existing_content or "No existing page — create from scratch.",
                    "new_fragments": all_fragments,
                    "fragment_count": len(all_fragments),
                    "existing_id": existing_id
                })
            elif existing_id:
                get_supabase().table('canonical_pages') \
                    .update({"is_current": False}) \
                    .eq('id', existing_id) \
                    .execute()
                print(f"Master Page Archived: {entity_name} — below threshold ({len(all_fragments)} fragments).")

        if not batch_payload:
            print("No data found to synthesize.")
            return

        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_chat_id and telegram_bot_token:
            try:
                url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
                payload = {"chat_id": int(telegram_chat_id), "text": f"Synthesizing {len(batch_payload)} Master Pages...", "parse_mode": "Markdown"}
                httpx.post(url, json=payload, timeout=10)
            except:
                pass

        print("Synthesizing Master Pages per entity...")
        results = {}
        for entry in batch_payload:
            entity_name = entry['entity']
            print(f"  Processing {entity_name} ({entry['fragment_count']} fragments)...")

            org_tag = entry.get('org_tag', '')
            is_parent = entry.get('is_parent', False)
            org_context = _get_org_tag_context().get(org_tag, org_tag)

            if is_parent:
                prompt_role = "Executive Summary Writer for {owner_name}'s OS"
                prompt_objective = f"Write a high-level overview of the {org_tag} domain ({entity_name}). Synthesize all sub-projects and activity under this domain."
                scope_rules = f"""DOMAIN SCOPE: This page covers the {org_tag} domain and its sub-projects only.
EXCLUDE: Any content related to other domains.
DOMAIN DESCRIPTION: {org_context}"""
            else:
                prompt_role = "Knowledge Curator for {owner_name}'s OS"
                prompt_objective = f"Update the Master Page for {entity_name} (under {org_tag})."
                scope_rules = f"""PROJECT SCOPE: This page is ONLY for {entity_name} under {org_tag}.
EXCLUDE: Any content about other projects, clients, or domains.
DOMAIN CONTEXT: {entity_name} belongs to {org_tag} ({org_context})."""

            per_prompt = render_prompt(f"""
ROLE: {prompt_role}
OBJECTIVE: {prompt_objective}

RULES:
- {scope_rules}
- CORRECT: If new fragments contradict the existing page, update with newer information.
- SPARSE GUARD: Output MUST be at least 300 characters. If fragments are thin, preserve the existing page as-is.
- FORMAT: Clean Markdown with headers and bullets.
- OUTPUT: Return ONLY the raw Markdown string. No JSON wrapper.

EXISTING PAGE:
{entry['existing_page']}

NEW FRAGMENTS:
{json.dumps(entry['new_fragments'], indent=2)}
""")
            try:
                response = await call_gemini_with_retry(
                    prompt=per_prompt,
                    model="gemini-3.1-flash-lite-preview",
                    config={'response_mime_type': 'text/plain'}
                )
                if response and response.text:
                    results[entity_name] = response.text.strip()
                else:
                    print(f"No response for {entity_name}, skipping.")
            except Exception as e:
                print(f"Gemini failed for {entity_name}: {e}")
                continue

        for entity_name, markdown in results.items():
            payload_entry = next((p for p in batch_payload if p['entity'] == entity_name), None)
            if not payload_entry:
                continue

            project_id = payload_entry['project_id']
            existing_id = payload_entry.get('existing_id')
            existing_content = payload_entry.get('existing_page', '')

            if len(markdown) < 300:
                print(f"Skipping {entity_name} — output too sparse ({len(markdown)} chars)")
                continue

            embedding = get_embedding(markdown)
            now_iso = datetime.now(timezone.utc).isoformat()

            try:
                if existing_id:
                    version_res = get_supabase().table('canonical_pages') \
                        .select('version') \
                        .eq('id', existing_id) \
                        .single() \
                        .execute()
                    old_version = (version_res.data.get('version') or 0) if version_res.data else 0

                    get_supabase().table('canonical_pages') \
                        .update({
                            "content": markdown,
                            "embedding": embedding,
                            "version": old_version + 1,
                            "updated_at": now_iso,
                            "source_count": payload_entry['fragment_count'],
                            "last_synth_at": now_iso,
                            "is_sparse": len(markdown) < 500
                        }) \
                        .eq('id', existing_id) \
                        .execute()

                    print(f"Master Page Updated: {entity_name} (v{old_version + 1}, {payload_entry['fragment_count']} fragments)")
                else:
                    get_supabase().table('canonical_pages').insert({
                        "title": entity_name,
                        "project_id": project_id,
                        "content": markdown,
                        "embedding": embedding,
                        "version": 1,
                        "is_current": True,
                        "updated_at": now_iso,
                        "source_count": payload_entry['fragment_count'],
                        "last_synth_at": now_iso,
                        "is_sparse": len(markdown) < 500
                    }).execute()
                    print(f"Master Page Created: {entity_name} ({payload_entry['fragment_count']} fragments)")
            except Exception as e:
                print(f"DB commit failed for {entity_name}: {e}")
                continue

    except Exception as e:
        print(f"Brain sweep failed: {e}")
        telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if telegram_chat_id and telegram_bot_token:
            try:
                url = f"https://api.telegram.org/bot{telegram_bot_token}/sendMessage"
                payload = {"chat_id": int(telegram_chat_id), "text": f"Brain Synthesizer failed: {str(e)[:100]}", "parse_mode": "Markdown"}
                httpx.post(url, json=payload, timeout=10)
            except:
                pass


if __name__ == "__main__":
    asyncio.run(run_batch_sweep())
