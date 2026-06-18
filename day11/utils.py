import os
import re
from typing import Dict, Optional

def parse_preferences_md(content: str) -> Dict[str, str]:
    """Парсинг MD файла с секциями ## STYLE, ## CONSTRAINTS, ## CONTEXT."""
    preferences = {}
    sections = ['STYLE', 'CONSTRAINTS', 'CONTEXT']
    
    for section in sections:
        pattern = f"## {section}\\s*\\n(.*?)(?=\\n## |\\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            preferences[section] = match.group(1).strip()
        else:
            preferences[section] = ""
    
    return preferences

def format_preferences_md(preferences: Dict[str, str]) -> str:
    """Форматирование предпочтений в MD формат."""
    sections = ['STYLE', 'CONSTRAINTS', 'CONTEXT']
    parts = []
    
    for section in sections:
        content = preferences.get(section, "")
        if content:
            parts.append(f"## {section}\n{content}")
        else:
            parts.append(f"## {section}\n(не указано)")
    
    return "\n\n".join(parts)

def get_user_name_from_preferences(preferences_file: str) -> Optional[str]:
    """Извлечение имени пользователя из файла предпочтений."""
    if not os.path.exists(preferences_file):
        return None
    
    with open(preferences_file, 'r', encoding='utf-8') as f:
        content = f.read()
        match = re.search(r"^# (.+)$", content, re.MULTILINE)
        if match:
            return match.group(1).strip()
    return None