DEFAULT_DOMAINS = [
    {
        "tag": "WORK",
        "name": "Work",
        "description": "Your work and professional tasks. Clients, projects, development, career.",
        "context": "work",
        "icon": "\U0001f4bc",
        "is_default": True,
    },
    {
        "tag": "PERSONAL",
        "name": "Personal",
        "description": "Family, home, health, personal admin, hobbies, learning.",
        "context": "personal",
        "icon": "\U0001f3e0",
    },
]


def get_default_tag(config):
    for d in config:
        if d.get("is_default"):
            return d["tag"]
    return config[0]["tag"] if config else "WORK"


def valid_tags(config):
    return [d["tag"] for d in config]


def context_map(config):
    return {d["tag"]: d.get("context", "work") for d in config}


def render_domain_block(config):
    lines = []
    for d in config:
        tag = d["tag"]
        parent = d.get("parent_project_name") or d.get("name", tag)
        description = d.get("description", "")
        ctx = d.get("context", "work")
        lines.append(
            f'  {tag:10s} | context: {ctx:<8s} | {description} \u2192 Set org_tag: "{tag}", parent_project_name: "{parent}"'
        )
    return "\n\n".join(lines)


def render_routing_rules(config):
    lines = ["ROUTING RULES (apply in order):"]
    for i, d in enumerate(config, 1):
        tag = d["tag"]
        description = d.get("description", "").split(".")[0].strip()
        lines.append(f"  {i}. Does the input mention {description.lower()}? \u2192 {tag}")
    default_tag = get_default_tag(config)
    lines.append(f"  {len(config) + 1}. Default for anything that doesn't fit above: \u2192 {default_tag}")
    return "\n".join(lines)


def render_entity_list(config):
    tags = valid_tags(config)
    return "|".join(tags + ["INBOX"])


def render_project_routing(config):
    lines = []
    for d in config:
        tag = d["tag"]
        description = d.get("description", "")
        lines.append(f"Route {description.lower()} to {tag}.")
    return " ".join(lines)


def render_stealth_routing(config):
    tags = valid_tags(config)
    names = ", ".join(tags)
    return f"Assign the entity in the JSON, but NEVER mention it ({names}) in the receipt text."
