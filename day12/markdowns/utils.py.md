# Overview
Utilities for parsing, formatting, and managing user preferences in Markdown sections.

## Imports
- `os`
- `re`
- `typing.Dict`, `typing.Optional`

## API
- `parse_preferences_md(content: str) -> Dict[str, str]` – Extract `STYLE`, `CONSTRAINTS`, `CONTEXT` sections from markdown.
- `format_preferences_md(preferences: Dict[str, str], name: str = "") -> str` – Rebuild markdown from dict, optional top-level `# name`.
- `get_user_name_from_preferences(preferences_file: str) -> Optional[str]` – Read file and extract first line `# name`.

## Usage
```python
from utils import parse_preferences_md, format_preferences_md, get_user_name_from_preferences

md = "## STYLE\nformal\n## CONSTRAINTS\nshort"
prefs = parse_preferences_md(md)                  # {'STYLE':'formal','CONSTRAINTS':'short','CONTEXT':''}
out = format_preferences_md(prefs, "Alice")       # "# Alice\n\n## STYLE\nformal\n..."
name = get_user_name_from_preferences("prefs.md") # "Alice" or None
```

## Notes
- Sections are case‑insensitive (`## style` works).
- Pattern stops at next `##` or end‑of‑string; nested hashes not supported.
- `format_preferences_md` omits `(не указано)` for empty sections – uses literal `(не указано)` if blank.
- `get_user_name_from_preferences` requires a `# Title` on its own line at the start; returns `None` if file missing.