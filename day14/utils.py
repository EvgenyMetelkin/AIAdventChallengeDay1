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

def parse_invariants_md(content: str) -> List[str]:
    """Parse an invariants markdown file into a list of individual invariant strings.

    The file uses a Markdown bulleted list format. Each top-level `-` line
    (or numbered `1.` line) is treated as one invariant. Multi-line entries
    (continuation lines beginning with whitespace) are folded into the
    preceding bullet.

    Args:
        content: Raw markdown content of invariants.md

    Returns:
        List of invariant strings (one per bullet)
    """
    if not content or not content.strip():
        return []

    invariants = []
    lines = content.strip().split("\n")
    current = None

    for line in lines:
        stripped = line.strip()
        # Skip empty lines and markdown headings
        if not stripped or stripped.startswith("#"):
            continue
        # Start a new bullet on - or 1. patterns
        if re.match(r"^[-*]\s+", stripped) or re.match(r"^\d+[.)]\s+", stripped):
            # Flush previous
            if current is not None:
                invariants.append(current.strip())
            # Remove the bullet marker
            current = re.sub(r"^[-*\d]+[.)]?\s+", "", stripped)
        elif current is not None:
            # Continuation line
            current += " " + stripped

    if current is not None:
        invariants.append(current.strip())

    return invariants


def format_invariants_prompt(invariants: List[str]) -> str:
    """Format invariants as a block for injection into LLM system prompts.

    Args:
        invariants: List of invariant strings

    Returns:
        Formatted prompt block (empty string if no invariants)
    """
    if not invariants:
        return ""

    lines = [
        "## ИНВАРИАНТЫ (ЖЁСТКИЕ ОГРАНИЧЕНИЯ)",
        "",
        "Ниже перечислены инварианты, которые ты ОБЯЗАН соблюдать при формировании ответа.",
        "Нарушение любого из них недопустимо. В своём ответе явно укажи, что ты учёл",
        "каждый инвариант, и объясни, как твой результат им соответствует.",
        "",
    ]
    for i, inv in enumerate(invariants, 1):
        lines.append(f"{i}. {inv}")

    lines.append("")
    return "\n".join(lines)


def format_invariant_check_prompt(invariants: List[str], artifact_text: str) -> str:
    """Format a prompt for checking whether an artifact violates invariants.

    Args:
        invariants: List of invariant strings
        artifact_text: The text of the artifact to check

    Returns:
        Prompt string for the invariant checker agent
    """
    if not invariants:
        return ""

    inv_list = "\n".join(f"{i}. {inv}" for i, inv in enumerate(invariants, 1))

    return f"""Оцени, соответствует ли следующий текст каждому из перечисленных инвариантов.

## Инварианты
{inv_list}

## Проверяемый текст
{artifact_text}

## Инструкции
Для каждого инварианта проверь, нарушается ли он в тексте. Если нарушений нет, верни пустой список.
Если есть нарушения, укажи конкретный инвариант и причину нарушения.

Ответь строго в формате JSON БЕЗ маркдаун-обёртки (без ```):
{{"violations": [{{"invariant": "текст инварианта", "reason": "почему нарушен"}}]}}
При отсутствии нарушений: {{"violations": []}}"""


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