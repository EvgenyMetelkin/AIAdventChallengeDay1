import os
import json
import uuid
import re
from typing import Dict, List, Optional
from dataclasses import dataclass, field

# Импортируем утилиты из utils
from utils import parse_preferences_md, format_preferences_md

@dataclass
class User:
    """Класс пользователя с предпочтениями и историей."""
    user_id: str
    name: str
    preferences: Dict[str, str] = field(default_factory=dict)
    history: List[Dict[str, str]] = field(default_factory=list)
    history_file: Optional[str] = None
    preferences_file: Optional[str] = None
    
    def __post_init__(self):
        """Автоматическая загрузка истории и предпочтений при инициализации."""
        if self.preferences_file and os.path.exists(self.preferences_file):
            self.load_preferences()
        if self.history_file and os.path.exists(self.history_file):
            self.load_history()
    
    def load_preferences(self):
        """Загрузка предпочтений из файла."""
        if not self.preferences_file or not os.path.exists(self.preferences_file):
            return
        
        with open(self.preferences_file, 'r', encoding='utf-8') as f:
            content = f.read()
        
        self.preferences = parse_preferences_md(content)
        # Убеждаемся, что все ключи существуют
        for key in ['STYLE', 'CONSTRAINTS', 'CONTEXT']:
            if key not in self.preferences:
                self.preferences[key] = ""
    
    def load_history(self):
        """Загрузка истории из JSON файла."""
        if not self.history_file or not os.path.exists(self.history_file):
            return
        
        with open(self.history_file, 'r', encoding='utf-8') as f:
            self.history = json.load(f)
    
    def save_history(self):
        """Сохранение истории в JSON файл."""
        if not self.history_file:
            return
        
        os.makedirs(os.path.dirname(self.history_file), exist_ok=True)
        with open(self.history_file, 'w', encoding='utf-8') as f:
            json.dump(self.history, f, ensure_ascii=False, indent=2)
    
    def save_preferences(self):
        """Сохранение предпочтений в MD файл."""
        if not self.preferences_file:
            return
        
        os.makedirs(os.path.dirname(self.preferences_file), exist_ok=True)
        content = format_preferences_md(self.preferences, self.name)
        with open(self.preferences_file, 'w', encoding='utf-8') as f:
            f.write(content)
    
    def get_system_prompt(self) -> str:
        """Формирование system-промпта из предпочтений."""
        parts = []
        if self.preferences.get('STYLE') and self.preferences['STYLE'].strip():
            parts.append(f"## STYLE\n{self.preferences['STYLE'].strip()}")
        if self.preferences.get('CONSTRAINTS') and self.preferences['CONSTRAINTS'].strip():
            parts.append(f"## CONSTRAINTS\n{self.preferences['CONSTRAINTS'].strip()}")
        if self.preferences.get('CONTEXT') and self.preferences['CONTEXT'].strip():
            parts.append(f"## CONTEXT\n{self.preferences['CONTEXT'].strip()}")
        
        # Если есть части, объединяем их с общим заголовком
        if parts:
            return "# System Instructions\n\n" + "\n\n".join(parts)
        return ""
    
    def reset_history(self):
        """Сброс истории."""
        self.history = []
        self.save_history()
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь для API."""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "preferences": self.preferences,
            "history_length": len(self.history)
        }


def create_user(user_dir: str, name: str, preferences_content: Optional[str] = None) -> User:
    """Создание нового пользователя."""
    user_id = uuid.uuid4().hex[:8]
    user_path = os.path.join(user_dir, user_id)
    os.makedirs(user_path, exist_ok=True)
    
    preferences_file = os.path.join(user_path, "preferences.md")
    history_file = os.path.join(user_path, "history.json")
    
    # Парсим предпочтения, если они переданы
    preferences = {}
    if preferences_content:
        preferences = parse_preferences_md(preferences_content)
    else:
        preferences = {"STYLE": "", "CONSTRAINTS": "", "CONTEXT": ""}
    
    user = User(
        user_id=user_id,
        name=name,
        preferences=preferences,
        history=[],
        history_file=history_file,
        preferences_file=preferences_file
    )
    
    user.save_preferences()
    user.save_history()
    
    return user


def load_all_users(user_dir: str) -> Dict[str, User]:
    """Загрузка всех пользователей из директории."""
    users = {}
    
    if not os.path.exists(user_dir):
        os.makedirs(user_dir, exist_ok=True)
        return users
    
    for user_id in os.listdir(user_dir):
        user_path = os.path.join(user_dir, user_id)
        if not os.path.isdir(user_path):
            continue
        
        preferences_file = os.path.join(user_path, "preferences.md")
        history_file = os.path.join(user_path, "history.json")
        
        # Читаем имя из preferences или используем ID
        name = user_id
        if os.path.exists(preferences_file):
            with open(preferences_file, 'r', encoding='utf-8') as f:
                content = f.read()
                # Ищем строку с именем в формате # Имя
                match = re.search(r"^# (.+)$", content, re.MULTILINE)
                if match:
                    name = match.group(1).strip()
        
        user = User(
            user_id=user_id,
            name=name,
            preferences={},
            history=[],
            history_file=history_file,
            preferences_file=preferences_file
        )
        # Загрузка произойдет автоматически в __post_init__
        users[user_id] = user
    
    return users


def create_default_user(user_dir: str) -> User:
    """Создание пользователя по умолчанию."""
    default_preferences = """# Пользователь по умолчанию

## STYLE
Отвечать формально, кратко, с примерами кода.

## CONSTRAINTS
Использовать только Python и JavaScript. Минимум зависимостей.

## CONTEXT
Senior Developer, интересуюсь LLM.
"""
    return create_user(user_dir, "Default User", default_preferences)