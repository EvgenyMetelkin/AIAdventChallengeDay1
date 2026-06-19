import os
import re
import logging
from typing import Dict, List, Optional

# Настройка логирования
logger = logging.getLogger(__name__)

def parse_preferences_md(content: str) -> Dict[str, str]:
    """Парсинг MD файла с секциями ## STYLE, ## CONSTRAINTS, ## CONTEXT."""
    preferences = {}
    sections = ['STYLE', 'CONSTRAINTS', 'CONTEXT']
    
    for section in sections:
        # Ищем секцию ## SECTION (с учетом возможных пробелов)
        pattern = f"##\\s*{section}\\s*\\n(.*?)(?=\\n\\s*##|\\Z)"
        match = re.search(pattern, content, re.DOTALL | re.IGNORECASE)
        if match:
            preferences[section] = match.group(1).strip()
        else:
            preferences[section] = ""
    
    return preferences

def format_preferences_md(preferences: Dict[str, str], name: str = "") -> str:
    """Форматирование предпочтений в MD формат."""
    parts = []
    
    # Добавляем заголовок с именем
    if name:
        parts.append(f"# {name}")
    else:
        parts.append("# Пользователь")
    
    sections = ['STYLE', 'CONSTRAINTS', 'CONTEXT']
    
    for section in sections:
        content = preferences.get(section, "")
        if content and content.strip():
            parts.append(f"## {section}\n{content.strip()}")
        else:
            parts.append(f"## {section}\n(не указано)")
    
    return "\n\n".join(parts)

def get_user_name_from_preferences(preferences_file: str) -> Optional[str]:
    """Извлечение имени пользователя из файла предпочтений."""
    if not os.path.exists(preferences_file):
        return None
    
    try:
        with open(preferences_file, 'r', encoding='utf-8') as f:
            content = f.read()
            match = re.search(r"^# (.+)$", content, re.MULTILINE)
            if match:
                return match.group(1).strip()
    except Exception as e:
        logger.error(f"Error reading preferences file {preferences_file}: {e}")
    
    return None

async def generate_summary(history: List[Dict], agent) -> str:
    """
    Генерирует краткую сводку истории диалога с помощью LLM.
    
    Args:
        history: список сообщений в формате [{"role": "...", "content": "..."}]
        agent: экземпляр Agent для выполнения запроса
        
    Returns:
        str: краткая сводка диалога
    """
    if not history:
        return ""
    
    # Формируем текст диалога для сводки
    dialog_text = "\n".join(
        f"{msg['role'].upper()}: {msg['content']}" 
        for msg in history
    )
    
    # Создаём специальный промпт для генерации сводки
    prompt = f"""Сделай краткую сводку следующего диалога, выдели основные решённые задачи и принятые решения.

Диалог:
{dialog_text}

Сводка:"""
    
    try:
        # Используем специальный метод для генерации сводки
        # Передаём промпт напрямую без использования истории
        response = await agent.send_message_without_history(prompt)
        return response.strip()
    except Exception as e:
        logger.error(f"Failed to generate summary: {e}")
        # Возвращаем базовую сводку в случае ошибки
        return f"[Сводка не сгенерирована: {str(e)}]"