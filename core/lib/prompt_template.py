from core.services.db import get_supabase, get_current_user_id
from core.lib.domain_utils import (
    DEFAULT_DOMAINS,
    render_domain_block,
    render_routing_rules,
    render_entity_list,
    render_project_routing,
    render_stealth_routing,
    valid_tags,
    context_map,
    get_default_tag,
)


def get_persona_context(user_id: str = None) -> dict:
    if not user_id:
        user_id = get_current_user_id()
    if not user_id:
        return {
            "owner_name": "User",
            "owner_full_name": "",
            "company_name": "",
            "location": "",
            "domains_config": DEFAULT_DOMAINS,
            "domain_block": render_domain_block(DEFAULT_DOMAINS),
            "routing_rules": render_routing_rules(DEFAULT_DOMAINS),
            "entity_list": render_entity_list(DEFAULT_DOMAINS),
            "project_routing": render_project_routing(DEFAULT_DOMAINS),
            "stealth_routing": render_stealth_routing(DEFAULT_DOMAINS),
            "default_domain_tag": get_default_tag(DEFAULT_DOMAINS),
        }
    profile = get_supabase().table('user_profiles')\
        .select('*').eq('user_id', user_id).maybe_single().execute()
    if not profile.data:
        return {
            "owner_name": "User",
            "owner_full_name": "",
            "company_name": "",
            "location": "",
            "domains_config": DEFAULT_DOMAINS,
            "domain_block": render_domain_block(DEFAULT_DOMAINS),
            "routing_rules": render_routing_rules(DEFAULT_DOMAINS),
            "entity_list": render_entity_list(DEFAULT_DOMAINS),
            "project_routing": render_project_routing(DEFAULT_DOMAINS),
            "stealth_routing": render_stealth_routing(DEFAULT_DOMAINS),
            "default_domain_tag": get_default_tag(DEFAULT_DOMAINS),
        }
    p = profile.data
    config = p.get("domains_config") or DEFAULT_DOMAINS
    return {
        "owner_name": p.get("owner_name", "User"),
        "owner_full_name": p.get("owner_full_name") or p.get("owner_name", ""),
        "company_name": p.get("company_name") or "",
        "location": p.get("location") or "",
        "domains_config": config,
        "domain_block": render_domain_block(config),
        "routing_rules": render_routing_rules(config),
        "entity_list": render_entity_list(config),
        "project_routing": render_project_routing(config),
        "stealth_routing": render_stealth_routing(config),
        "default_domain_tag": get_default_tag(config),
    }


def render_prompt(template: str, user_id: str = None) -> str:
    ctx = get_persona_context(user_id)
    return template.format(**ctx)
