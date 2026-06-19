import os
import json
import uuid
import re
import shutil
import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

from utils import parse_preferences_md, format_preferences_md, generate_summary

# Настройка логирования
logger = logging.getLogger(__name__)

@dataclass
class User:
    """Класс пользователя с предпочтениями, историей и рабочей памятью."""
    user_id: str
    name: str
    preferences: Dict[str, str] = field(default_factory=dict)
    working_memory: List[str] = field(default_factory=list)
    agents: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    current_agent_id: Optional[str] = None
    user_dir: Optional[str] = None
    preferences_file: Optional[str] = None
    
    def __post_init__(self):
        """Автоматическая загрузка данных при инициализации."""
        if self.user_dir:
            self._ensure_directories()
            self.load_preferences()
            self.load_working_memory()
            self.load_agents()
        elif self.preferences_file:
            self.user_dir = os.path.dirname(self.preferences_file)
            self._ensure_directories()
            self.load_preferences()
            self.load_working_memory()
            self.load_agents()
    
    def _ensure_directories(self):
        """Создание необходимых директорий."""
        if not self.user_dir:
            return
        os.makedirs(self.user_dir, exist_ok=True)
        agents_dir = os.path.join(self.user_dir, "agents")
        os.makedirs(agents_dir, exist_ok=True)
    
    def _get_agent_dir(self, agent_id: str) -> str:
        """Получить путь к директории агента."""
        return os.path.join(self.user_dir, "agents", agent_id)
    
    def _get_agent_history_path(self, agent_id: str) -> str:
        """Получить путь к файлу истории агента."""
        return os.path.join(self._get_agent_dir(agent_id), "history.json")
    
    def _get_agent_metadata_path(self, agent_id: str) -> str:
        """Получить путь к файлу метаданных агента."""
        return os.path.join(self._get_agent_dir(agent_id), "metadata.json")
    
    def _get_working_memory_path(self) -> str:
        """Получить путь к файлу рабочей памяти."""
        return os.path.join(self.user_dir, "working_memory.json")
    
    # === Загрузка/сохранение ===
    
    def load_preferences(self):
        """Загрузка предпочтений из файла."""
        if not self.preferences_file or not os.path.exists(self.preferences_file):
            return
        
        try:
            with open(self.preferences_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            self.preferences = parse_preferences_md(content)
            for key in ['STYLE', 'CONSTRAINTS', 'CONTEXT']:
                if key not in self.preferences:
                    self.preferences[key] = ""
        except Exception as e:
            logger.error(f"Error loading preferences for {self.name}: {e}")
            self.preferences = {"STYLE": "", "CONSTRAINTS": "", "CONTEXT": ""}
    
    def save_preferences(self):
        """Сохранение предпочтений в MD файл."""
        if not self.preferences_file:
            return
        
        try:
            os.makedirs(os.path.dirname(self.preferences_file), exist_ok=True)
            content = format_preferences_md(self.preferences, self.name)
            with open(self.preferences_file, 'w', encoding='utf-8') as f:
                f.write(content)
        except Exception as e:
            logger.error(f"Error saving preferences for {self.name}: {e}")
    
    def load_working_memory(self):
        """Загрузка рабочей памяти из файла."""
        path = self._get_working_memory_path()
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    self.working_memory = data.get('summaries', [])
            except Exception as e:
                logger.error(f"Error loading working memory for {self.name}: {e}")
                self.working_memory = []
        else:
            self.working_memory = []
    
    def save_working_memory(self):
        """Сохранение рабочей памяти в файл."""
        if not self.user_dir:
            return
        
        path = self._get_working_memory_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, 'w', encoding='utf-8') as f:
                json.dump({
                    'user_id': self.user_id,
                    'summaries': self.working_memory,
                    'updated_at': str(__import__('datetime').datetime.now())
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Error saving working memory for {self.name}: {e}")
    
    def load_agents(self):
        """Загрузка всех агентов пользователя."""
        if not self.user_dir:
            return
            
        agents_dir = os.path.join(self.user_dir, "agents")
        self.agents = {}
        
        if os.path.exists(agents_dir):
            for agent_dir in os.listdir(agents_dir):
                agent_path = os.path.join(agents_dir, agent_dir)
                if not os.path.isdir(agent_path):
                    continue
                
                try:
                    # Загружаем метаданные
                    metadata_path = os.path.join(agent_path, "metadata.json")
                    if os.path.exists(metadata_path):
                        with open(metadata_path, 'r', encoding='utf-8') as f:
                            metadata = json.load(f)
                    else:
                        metadata = {"name": agent_dir, "created": ""}
                    
                    # Загружаем историю
                    history_path = os.path.join(agent_path, "history.json")
                    if os.path.exists(history_path):
                        with open(history_path, 'r', encoding='utf-8') as f:
                            history = json.load(f)
                    else:
                        history = []
                    
                    self.agents[agent_dir] = {
                        'name': metadata.get('name', agent_dir),
                        'created': metadata.get('created', ''),
                        'history': history
                    }
                except Exception as e:
                    logger.error(f"Error loading agent {agent_dir}: {e}")
                    continue
        
        # Если агентов нет, создаём агента по умолчанию
        if not self.agents:
            default_id = self.add_agent("default")
            self.current_agent_id = default_id
        elif self.current_agent_id is None or self.current_agent_id not in self.agents:
            # Если текущий агент не установлен или не существует, берём первый
            self.current_agent_id = list(self.agents.keys())[0]
    
    def save_agents(self):
        """Сохранение всех агентов."""
        if not self.user_dir:
            return
            
        for agent_id, agent_data in self.agents.items():
            try:
                agent_dir = self._get_agent_dir(agent_id)
                os.makedirs(agent_dir, exist_ok=True)
                
                # Сохраняем историю
                history_path = self._get_agent_history_path(agent_id)
                with open(history_path, 'w', encoding='utf-8') as f:
                    json.dump(agent_data['history'], f, ensure_ascii=False, indent=2)
                
                # Сохраняем метаданные
                metadata_path = self._get_agent_metadata_path(agent_id)
                with open(metadata_path, 'w', encoding='utf-8') as f:
                    json.dump({
                        'name': agent_data['name'],
                        'created': agent_data.get('created', ''),
                    }, f, ensure_ascii=False, indent=2)
            except Exception as e:
                logger.error(f"Error saving agent {agent_id}: {e}")
    
    # === Управление агентами ===
    
    def add_agent(self, name: str) -> str:
        """Создание нового агента."""
        agent_id = uuid.uuid4().hex[:8]
        self.agents[agent_id] = {
            'name': name,
            'created': str(__import__('datetime').datetime.now()),
            'history': []
        }
        self.save_agents()
        return agent_id
    
    def get_current_history(self) -> List[Dict]:
        """Получить историю текущего агента."""
        if self.current_agent_id is None or self.current_agent_id not in self.agents:
            return []
        return self.agents[self.current_agent_id]['history']
    
    def set_current_history(self, history: List[Dict]):
        """Установить историю для текущего агента."""
        if self.current_agent_id is not None and self.current_agent_id in self.agents:
            self.agents[self.current_agent_id]['history'] = history
            self.save_agents()
    
    def append_to_history(self, message: Dict):
        """Добавить сообщение в историю текущего агента."""
        if self.current_agent_id is not None and self.current_agent_id in self.agents:
            self.agents[self.current_agent_id]['history'].append(message)
            self.save_agents()
    
    async def switch_agent(self, agent_id: str, agent_instance) -> str:
        """
        Переключение на другого агента с генерацией сводки текущей истории.
    
        Returns:
            str: сгенерированная сводка (или пустая строка)
        """
        if agent_id not in self.agents:
            raise ValueError(f"Agent {agent_id} not found")

        current_history = self.get_current_history()
        summary = ""

        # Генерируем сводку текущей истории, если она не пуста
        if current_history and agent_instance:
            try:
                # Используем обновленную функцию generate_summary
                summary = await generate_summary(current_history, agent_instance)
                if summary:
                    self.working_memory.append(summary)
                    self.save_working_memory()
                    logger.info(f"Added summary to working memory for {self.name}: {summary[:100]}...")
            except Exception as e:
                logger.error(f"Failed to generate summary for {self.name}: {e}")
                # Продолжаем переключение даже если сводка не сгенерировалась

        # Переключаемся на нового агента
        self.current_agent_id = agent_id
        self.save_agents()
    
        return summary
    
    def delete_agent(self, agent_id: str) -> bool:
        """
        Удаление агента.
        
        Returns:
            bool: True если удаление успешно, False если это последний агент
        """
        if len(self.agents) <= 1:
            return False
        
        if agent_id not in self.agents:
            return False
        
        # Если удаляем текущего агента, переключаемся на другого
        if self.current_agent_id == agent_id:
            # Выбираем первого попавшегося другого агента
            new_agent_id = next(aid for aid in self.agents.keys() if aid != agent_id)
            self.current_agent_id = new_agent_id
        
        # Удаляем директорию агента
        if self.user_dir:
            agent_dir = self._get_agent_dir(agent_id)
            if os.path.exists(agent_dir):
                try:
                    shutil.rmtree(agent_dir)
                except Exception as e:
                    logger.error(f"Error deleting agent directory {agent_dir}: {e}")
        
        # Удаляем из словаря
        del self.agents[agent_id]
        self.save_agents()
        
        return True
    
    def reset_current_history(self):
        """Сброс истории текущего агента."""
        if self.current_agent_id is not None and self.current_agent_id in self.agents:
            self.agents[self.current_agent_id]['history'] = []
            self.save_agents()
    
    def get_system_prompt(self) -> str:
        """Формирование system-промпта из предпочтений."""
        parts = []
        if self.preferences.get('STYLE') and self.preferences['STYLE'].strip():
            parts.append(f"## STYLE\n{self.preferences['STYLE'].strip()}")
        if self.preferences.get('CONSTRAINTS') and self.preferences['CONSTRAINTS'].strip():
            parts.append(f"## CONSTRAINTS\n{self.preferences['CONSTRAINTS'].strip()}")
        if self.preferences.get('CONTEXT') and self.preferences['CONTEXT'].strip():
            parts.append(f"## CONTEXT\n{self.preferences['CONTEXT'].strip()}")
        
        if parts:
            return "# System Instructions\n\n" + "\n\n".join(parts)
        return ""
    
    def to_dict(self) -> Dict:
        """Преобразование в словарь для API."""
        return {
            "user_id": self.user_id,
            "name": self.name,
            "preferences": self.preferences,
            "agents": {
                aid: {
                    "name": data["name"],
                    "history_length": len(data["history"])
                }
                for aid, data in self.agents.items()
            },
            "current_agent_id": self.current_agent_id,
            "working_memory_length": len(self.working_memory)
        }


# Функции для работы с пользователями

def create_user(user_dir: str, name: str, preferences_content: Optional[str] = None) -> User:
    """Создание нового пользователя."""
    user_id = uuid.uuid4().hex[:8]
    user_path = os.path.join(user_dir, user_id)
    os.makedirs(user_path, exist_ok=True)
    os.makedirs(os.path.join(user_path, "agents"), exist_ok=True)
    
    preferences_file = os.path.join(user_path, "preferences.md")
    
    # Парсим предпочтения, если они переданы
    preferences = {}
    if preferences_content:
        try:
            preferences = parse_preferences_md(preferences_content)
        except Exception as e:
            logger.error(f"Error parsing preferences: {e}")
            preferences = {"STYLE": "", "CONSTRAINTS": "", "CONTEXT": ""}
    else:
        preferences = {"STYLE": "", "CONSTRAINTS": "", "CONTEXT": ""}
    
    user = User(
        user_id=user_id,
        name=name,
        preferences=preferences,
        user_dir=user_path,
        preferences_file=preferences_file
    )
    
    # Создаём агента по умолчанию
    default_agent_id = user.add_agent("default")
    user.current_agent_id = default_agent_id
    
    user.save_preferences()
    user.save_agents()
    user.save_working_memory()
    
    logger.info(f"Created user: {name} ({user_id}) with default agent")
    
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
        
        # Читаем имя из preferences или используем ID
        name = user_id
        if os.path.exists(preferences_file):
            try:
                with open(preferences_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    match = re.search(r"^# (.+)$", content, re.MULTILINE)
                    if match:
                        name = match.group(1).strip()
            except Exception as e:
                logger.error(f"Error reading preferences for {user_id}: {e}")
        
        try:
            user = User(
                user_id=user_id,
                name=name,
                user_dir=user_path,
                preferences_file=preferences_file
            )
            # Загрузка произойдет автоматически в __post_init__
            users[user_id] = user
            logger.info(f"Loaded user: {name} ({user_id}) with {len(user.agents)} agents")
        except Exception as e:
            logger.error(f"Error loading user {user_id}: {e}")
            continue
    
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