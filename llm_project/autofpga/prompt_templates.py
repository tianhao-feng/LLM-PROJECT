import os


PROMPT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompts")


def load_prompt_template(template_name):
    path = os.path.join(PROMPT_DIR, template_name)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def render_prompt(template_name, **values):
    template = load_prompt_template(template_name)
    try:
        return template.format(**values)
    except KeyError as exc:
        missing = exc.args[0]
        raise KeyError(f"prompt template {template_name} missing value: {missing}") from exc


def parse_prompt_metadata(text):
    metadata = {}
    for line in (text or "").splitlines()[:10]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        if key in {"prompt_name", "prompt_version"}:
            metadata[key] = value.strip()
    return metadata
