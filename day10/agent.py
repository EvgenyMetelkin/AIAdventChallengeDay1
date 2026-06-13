import json
import os
import logging
import uuid
import glob
import base64
from typing import List, Dict, Optional, Any, Union, Tuple
import httpx
from pathlib import Path
import asyncio
from datetime import datetime

class Agent:
    """Агент для взаимодействия с LLM через OpenAI‑совместимый API с поддержкой файлов и умным управлением контекстом."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-3.5-turbo", temperature: float = 0.7,
                 max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False,
                 agent_id: Optional[str] = None, history_dir: str = "agent_history",
                 files_dir: str = "agent_files", max_file_size_mb: int = 10,
                 keep_last_n_messages: int = 10, summary_interval: int = 10,
                 context_strategy: str = "summary"):
        # Настройка логгирования
        self.verbose = verbose
        if verbose:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = None
        
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.history_dir = history_dir
        self.files_dir = files_dir
        self.max_file_size_mb = max_file_size_mb
        
        # Настройки контекста
        self.keep_last_n = keep_last_n_messages
        self.summary_interval = summary_interval
        self.context_strategy = context_strategy
        
        # Для стратегии Summary
        self.summaries: List[str] = []
        
        # Для стратегии Sticky Facts
        self.facts: Dict[str, Any] = {}
        
        # Для стратегии Branching
        self.branches: Dict[str, Dict] = {}
        self.current_branch: str = "main"
        
        # Инициализируем главную ветку
        self.branches[self.current_branch] = {
            "history": [],
            "facts": {},
            "summaries": [],
            "last_used": datetime.now().isoformat()
        }
        
        # Счетчик всех токенов за сессию
        self.total_tokens_used: int = 0
        
        # Статистика последнего запроса
        self.last_prompt_tokens: int = 0
        self.last_completion_tokens: int = 0
        self.last_total_tokens: int = 0
        
        # Генерация или использование указанного agent_id
        if agent_id is None:
            self.agent_id = uuid.uuid4().hex[:8]
            if verbose:
                print(f"Generated new agent_id: {self.agent_id}")
                self._log(f"Created new agent with ID: {self.agent_id}")
        else:
            self.agent_id = agent_id
            if verbose:
                self._log(f"Using provided agent ID: {self.agent_id}")
        
        # Создание директорий
        os.makedirs(self.history_dir, exist_ok=True)
        os.makedirs(self.files_dir, exist_ok=True)
        
        # Создание директории для файлов этого агента
        self.agent_files_dir = os.path.join(self.files_dir, self.agent_id)
        os.makedirs(self.agent_files_dir, exist_ok=True)
        
        # Формирование пути к файлу истории
        safe_model = self._sanitize_filename(self.model)
        safe_agent_id = self._sanitize_filename(self.agent_id)
        history_filename = f"history_{safe_agent_id}_{safe_model}.json"
        self._history_file_path = os.path.join(self.history_dir, history_filename)
        
        # Определение поддержки vision моделью
        self.supports_vision = any(x in model.lower() for x in ['vision', 'gpt-4', 'gpt-4o', 'claude-3'])
        
        # Автоматическая загрузка истории
        if os.path.exists(self._history_file_path):
            self.load_history(self._history_file_path)
            self._log(f"Loaded history for agent {self.agent_id} from {self._history_file_path}")
        else:
            self._log(f"No existing history found for agent {self.agent_id}, starting fresh")
            self._load_current_branch_data()

    def _load_current_branch_data(self):
        """Загружает данные текущей ветки в основные атрибуты."""
        if self.current_branch in self.branches:
            branch = self.branches[self.current_branch]
            self.conversation_history = branch.get("history", [])
            self.facts = branch.get("facts", {})
            self.summaries = branch.get("summaries", [])
        else:
            self.conversation_history = []
            self.facts = {}
            self.summaries = []

    def _save_current_branch_data(self):
        """Сохраняет данные из основных атрибутов в текущую ветку."""
        if self.current_branch not in self.branches:
            self.branches[self.current_branch] = {}
        
        self.branches[self.current_branch]["history"] = self.conversation_history
        self.branches[self.current_branch]["facts"] = self.facts
        self.branches[self.current_branch]["summaries"] = self.summaries
        self.branches[self.current_branch]["last_used"] = datetime.now().isoformat()

    def _sanitize_filename(self, filename: str) -> str:
        """Замена небезопасных символов для имени файла на подчёркивания."""
        unsafe_chars = '<>:"/\\|?*'
        for char in unsafe_chars:
            filename = filename.replace(char, '_')
        return filename

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger.info(msg)
        elif self.verbose:
            print(f"[LOG] {msg}")

    def _save_to_default_file(self) -> None:
        """Приватный метод для автоматического сохранения в дефолтный файл."""
        self.save_history(self._history_file_path)

    def set_context_strategy(self, strategy: str) -> None:
        """Изменяет стратегию управления контекстом."""
        valid_strategies = ["sliding_window", "sticky_facts", "branching", "summary"]
        if strategy not in valid_strategies:
            raise ValueError(f"Invalid strategy. Choose from: {valid_strategies}")
        
        old_strategy = self.context_strategy
        self.context_strategy = strategy
        
        # Адаптируем текущее состояние под новую стратегию
        if old_strategy != strategy:
            self._adapt_to_new_strategy()
        
        self._log(f"Context strategy changed from {old_strategy} to {strategy}")
        self._save_to_default_file()

    def _adapt_to_new_strategy(self) -> None:
        """Адаптирует текущее состояние под новую стратегию."""
        if self.context_strategy == "sliding_window":
            # Ограничиваем историю до keep_last_n
            if len(self.conversation_history) > self.keep_last_n:
                self.conversation_history = self.conversation_history[-self.keep_last_n:]
            # Очищаем факты и суммаризации
            self.facts = {}
            self.summaries = []
        
        elif self.context_strategy == "sticky_facts":
            # Извлекаем факты из существующей истории
            if self.conversation_history:
                asyncio.create_task(self._extract_facts_from_history())
        
        elif self.context_strategy == "branching":
            # Сохраняем текущее состояние в ветку
            self._save_current_branch_data()
        
        elif self.context_strategy == "summary":
            # Очищаем факты
            self.facts = {}
        
        self._save_current_branch_data()

    async def _extract_facts_from_history(self) -> None:
        """Извлекает факты из всей существующей истории."""
        if not self.conversation_history:
            return
        
        self._log("Extracting facts from existing history for sticky_facts strategy")
        
        # Формируем текст истории
        history_text = []
        for msg in self.conversation_history[-10:]:  # Берем последние 10 сообщений
            role = "User" if msg['role'] == 'user' else "Assistant"
            content = msg['content']
            if isinstance(content, str):
                history_text.append(f"{role}: {content}")
            elif isinstance(content, list):
                text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
                history_text.append(f"{role}: {' '.join(text_parts)}")
        
        if history_text:
            facts = await self._call_fact_extraction("\n".join(history_text))
            if facts:
                self.facts.update(facts)
                self._log(f"Extracted {len(facts)} facts from history")
                self._save_to_default_file()

    def reset_conversation(self) -> None:
        """Сброс истории диалога с очисткой JSON файла и обнулением статистики токенов."""
        import shutil
        if os.path.exists(self.agent_files_dir):
            shutil.rmtree(self.agent_files_dir)
            os.makedirs(self.agent_files_dir, exist_ok=True)
        
        # Сбрасываем текущую ветку
        self.conversation_history = []
        self.summaries = []
        self.facts = {}
        
        # Сбрасываем все ветки
        self.branches = {}
        self.current_branch = "main"
        self.branches[self.current_branch] = {
            "history": [],
            "facts": {},
            "summaries": [],
            "last_used": datetime.now().isoformat()
        }
        
        # Обнуляем статистику токенов
        self.total_tokens_used = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        
        self._save_to_default_file()
        self._log("Conversation history reset and files cleared. Token stats reset.")

    def _build_context_messages(self) -> List[Dict[str, Any]]:
        """Собирает контекст в зависимости от выбранной стратегии."""
        if self.context_strategy == "sliding_window":
            return self._build_sliding_window_context()
        elif self.context_strategy == "sticky_facts":
            return self._build_sticky_facts_context()
        elif self.context_strategy == "branching":
            return self._build_branching_context()
        else:  # summary (default)
            return self._build_summary_context()

    def _build_sliding_window_context(self) -> List[Dict[str, Any]]:
        """Скользящее окно: только последние N сообщений."""
        context = []
        recent_messages = self.conversation_history[-self.keep_last_n:] if self.conversation_history else []
        
        for msg in recent_messages:
            if msg['role'] == 'assistant':
                context.append({"role": "assistant", "content": msg['content']})
            else:
                content = msg['content']
                if isinstance(content, str):
                    context.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    if not self.supports_vision:
                        text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
                        context.append({"role": "user", "content": '\n'.join(text_parts) if text_parts else ""})
                    else:
                        context.append({"role": "user", "content": content})
                else:
                    context.append({"role": "user", "content": str(content)})
        
        return context

    def _build_sticky_facts_context(self) -> List[Dict[str, Any]]:
        """Sticky Facts: факты + последние N сообщений."""
        context = []
        
        # Добавляем факты как системное сообщение
        if self.facts:
            facts_text = "Known facts from conversation:\n"
            for key, value in self.facts.items():
                facts_text += f"- {key}: {value}\n"
            context.append({"role": "system", "content": facts_text})
        
        # Добавляем последние сообщения
        recent_messages = self.conversation_history[-self.keep_last_n:] if self.conversation_history else []
        
        for msg in recent_messages:
            if msg['role'] == 'assistant':
                context.append({"role": "assistant", "content": msg['content']})
            else:
                content = msg['content']
                if isinstance(content, str):
                    context.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    if not self.supports_vision:
                        text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
                        context.append({"role": "user", "content": '\n'.join(text_parts) if text_parts else ""})
                    else:
                        context.append({"role": "user", "content": content})
                else:
                    context.append({"role": "user", "content": str(content)})
        
        return context

    def _build_branching_context(self) -> List[Dict[str, Any]]:
        """Branching: использует текущую ветку (аналогично sliding_window)."""
        return self._build_sliding_window_context()

    def _build_summary_context(self) -> List[Dict[str, Any]]:
        """Summary: суммаризации + последние N сообщений."""
        context = []
        
        # Добавляем суммаризации как системные сообщения
        for i, summary in enumerate(self.summaries):
            context.append({
                "role": "system",
                "content": f"[Summary {i+1} of earlier conversation]: {summary}"
            })
        
        # Добавляем последние N сообщений
        recent_messages = self.conversation_history[-self.keep_last_n:] if self.conversation_history else []
        
        for msg in recent_messages:
            if msg['role'] == 'assistant':
                context.append({"role": "assistant", "content": msg['content']})
            else:
                content = msg['content']
                if isinstance(content, str):
                    context.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    if not self.supports_vision:
                        text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
                        context.append({"role": "user", "content": '\n'.join(text_parts) if text_parts else ""})
                    else:
                        context.append({"role": "user", "content": content})
                else:
                    context.append({"role": "user", "content": str(content)})
        
        return context

    async def send_message(self, user_message: str = "", files: Optional[List[Dict]] = None) -> Tuple[str, Dict[str, int]]:
        """Отправить сообщение LLM, получить ответ с статистикой токенов."""
        if files is None:
            files = []
        
        # Подготовка контента сообщения
        content = self._prepare_message_content(user_message, files)
        
        # Сохраняем сообщение пользователя
        user_message_obj = {
            "role": "user",
            "content": content,
            "attachments": [self._get_file_metadata(f) for f in files] if files else [],
            "tokens": None
        }
        self.conversation_history.append(user_message_obj)
        
        # Для стратегии sticky_facts обновляем факты после получения сообщения
        if self.context_strategy == "sticky_facts" and user_message:
            asyncio.create_task(self._update_facts_from_message(user_message_obj))
        
        # Собираем контекст
        context_messages = self._build_context_messages()
        
        # Добавляем последнее сообщение пользователя в контекст
        api_messages = context_messages + self._prepare_api_messages_for_context([user_message_obj])
        
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }
        
        self._log(f"Request to {url} with model {self.model}, strategy: {self.context_strategy}")
        self._log(f"Context size: {len(api_messages)} messages")
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
        except httpx.TimeoutException:
            raise Exception(f"Request timed out after {self.timeout} seconds.")
        except httpx.HTTPStatusError as e:
            try:
                error_detail = e.response.json().get('error', {}).get('message', str(e))
            except Exception:
                error_detail = str(e)
            raise Exception(f"HTTP error {e.response.status_code}: {error_detail}")
        except httpx.RequestError as e:
            raise Exception(f"Network error: {str(e)}")
        
        try:
            assistant_message = data['choices'][0]['message']['content']
        except (KeyError, IndexError) as e:
            raise Exception(f"Unexpected API response format: {data}")
        
        # Извлечение статистики токенов
        token_stats = self._extract_token_stats(data)
        
        # Обновляем общую статистику
        self.total_tokens_used += token_stats.get("total_tokens", 0)
        self.last_prompt_tokens = token_stats.get("prompt_tokens", 0)
        self.last_completion_tokens = token_stats.get("completion_tokens", 0)
        self.last_total_tokens = token_stats.get("total_tokens", 0)
        
        # Сохраняем сообщение ассистента
        assistant_message_obj = {
            "role": "assistant",
            "content": assistant_message,
            "tokens": token_stats
        }
        self.conversation_history.append(assistant_message_obj)
        
        # Для sticky_facts обновляем факты из ответа ассистента
        if self.context_strategy == "sticky_facts":
            asyncio.create_task(self._update_facts_from_message(assistant_message_obj))
        
        # Для стратегии summary запускаем суммаризацию
        if self.context_strategy == "summary":
            await self._maybe_summarize()
        
        # Для sliding_window обрезаем историю
        if self.context_strategy == "sliding_window":
            self._trim_history()
        
        # Сохраняем состояние
        self._save_current_branch_data()
        self._save_to_default_file()
        
        return assistant_message, self.get_token_stats()

    def _trim_history(self):
        """Обрезает историю для стратегии sliding_window."""
        if len(self.conversation_history) > self.keep_last_n:
            self.conversation_history = self.conversation_history[-self.keep_last_n:]

    async def _update_facts_from_message(self, message: Dict) -> None:
        """Обновляет факты на основе сообщения."""
        content = message.get('content', '')
        if isinstance(content, list):
            text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
            text = ' '.join(text_parts)
        else:
            text = str(content)
        
        if not text or len(text) < 10:
            return
        
        facts = await self._call_fact_extraction(text)
        if facts:
            self.facts.update(facts)
            self._log(f"Updated facts: {facts}")
            self._save_to_default_file()

    async def _call_fact_extraction(self, text: str) -> Optional[Dict]:
        """Вызывает LLM для извлечения фактов из текста."""
        fact_prompt = f"""Extract key facts from the following text. Return ONLY a JSON object with key-value pairs.
Do not add any explanation, only valid JSON.

Text: {text}

Example output: {{"user_goal": "want vegan dinner", "allergy": "nuts", "agreed_price": 1500}}

Facts:"""
        
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": "gpt-3.5-turbo",  # Use cheaper model for fact extraction
            "messages": [{"role": "user", "content": fact_prompt}],
            "temperature": 0.1,
            "max_tokens": 500
        }
        
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                result = data['choices'][0]['message']['content'].strip()
                # Try to parse JSON
                result = result.replace('```json', '').replace('```', '').strip()
                facts = json.loads(result)
                
                if isinstance(facts, dict):
                    return facts
                return None
                
        except Exception as e:
            self._log(f"Error extracting facts: {str(e)}")
            return None

    async def _maybe_summarize(self) -> None:
        """Проверяет необходимость суммаризации и выполняет её."""
        old_messages_count = max(0, len(self.conversation_history) - self.keep_last_n)
        
        while old_messages_count >= self.summary_interval:
            messages_to_summarize = self.conversation_history[:self.summary_interval]
            
            self._log(f"Summarizing {len(messages_to_summarize)} messages (batch of {self.summary_interval})")
            
            summary = await self._generate_summary(messages_to_summarize)
            
            if summary:
                self.summaries.append(summary)
                self.conversation_history = self.conversation_history[self.summary_interval:]
                self._log(f"Summarization successful. Removed {self.summary_interval} messages, added summary #{len(self.summaries)}")
            else:
                self._log("Summarization failed, will retry later")
                break
            
            old_messages_count = max(0, len(self.conversation_history) - self.keep_last_n)

    async def _generate_summary(self, messages: List[Dict]) -> Optional[str]:
        """Генерирует краткое изложение блока сообщений."""
        conversation_text = []
        for msg in messages:
            role = "Пользователь" if msg['role'] == 'user' else "Ассистент"
            content = msg['content']
            
            if isinstance(content, str):
                text = content
            elif isinstance(content, list):
                text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
                text = '\n'.join(text_parts) if text_parts else "[Не текстовое содержимое]"
            else:
                text = str(content)
            
            conversation_text.append(f"{role}: {text}")
        
        conversation_str = "\n".join(conversation_text)
        
        summary_prompt = f"""Сделай краткое изложение следующего фрагмента диалога. Сохрани ключевые факты, вопросы и ответы. Будь лаконичен. Изложение должно быть на том же языке, что и диалог.

Диалог:
{conversation_str}

Краткое изложение:"""
        
        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        payload = {
            "model": self.model,
            "messages": [{"role": "user", "content": summary_prompt}],
            "temperature": 0.3,
            "max_tokens": min(300, self.max_tokens)
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload, headers=headers)
                response.raise_for_status()
                data = response.json()
                
                summary = data['choices'][0]['message']['content'].strip()
                
                if 'usage' in data:
                    self.total_tokens_used += data['usage'].get('total_tokens', 0)
                
                self._log(f"Generated summary ({len(summary)} chars)")
                return summary
                
        except Exception as e:
            self._log(f"Error generating summary: {str(e)}")
            return None

    # Branching methods
    def save_checkpoint(self, name: str) -> None:
        """Сохраняет текущее состояние как новую ветку."""
        if not name or not name.strip():
            raise ValueError("Branch name cannot be empty")
        
        self._save_current_branch_data()
        
        if name not in self.branches:
            self.branches[name] = {}
        
        self.branches[name]["history"] = self.conversation_history.copy()
        self.branches[name]["facts"] = self.facts.copy()
        self.branches[name]["summaries"] = self.summaries.copy()
        self.branches[name]["last_used"] = datetime.now().isoformat()
        
        self._log(f"Saved checkpoint '{name}'")
        self._save_to_default_file()

    def switch_branch(self, name: str) -> None:
        """Переключается на другую ветку."""
        if not name or not name.strip():
            raise ValueError("Branch name cannot be empty")
        
        # Сохраняем текущую ветку
        self._save_current_branch_data()
        
        # Создаем новую ветку, если её нет
        if name not in self.branches:
            self.branches[name] = {
                "history": [],
                "facts": {},
                "summaries": [],
                "last_used": datetime.now().isoformat()
            }
        
        # Переключаемся
        self.current_branch = name
        self._load_current_branch_data()
        
        self._log(f"Switched to branch '{name}'")
        self._save_to_default_file()

    def list_branches(self) -> List[str]:
        """Возвращает список всех веток."""
        return list(self.branches.keys())

    def delete_branch(self, name: str) -> None:
        """Удаляет ветку."""
        if name not in self.branches:
            raise ValueError(f"Branch '{name}' not found")
        
        if name == self.current_branch:
            raise ValueError("Cannot delete current branch. Switch to another branch first.")
        
        del self.branches[name]
        self._log(f"Deleted branch '{name}'")
        self._save_to_default_file()

    def get_current_branch(self) -> str:
        """Возвращает имя текущей ветки."""
        return self.current_branch

    def _prepare_api_messages_for_context(self, messages: List[Dict]) -> List[Dict]:
        """Подготовка сообщений для API."""
        api_messages = []
        for msg in messages:
            if msg['role'] == 'assistant':
                api_messages.append({"role": "assistant", "content": msg['content']})
            else:
                content = msg['content']
                if isinstance(content, str):
                    api_messages.append({"role": "user", "content": content})
                elif isinstance(content, list):
                    if not self.supports_vision:
                        text_parts = [p.get('text', '') for p in content if isinstance(p, dict) and p.get('type') == 'text']
                        api_messages.append({"role": "user", "content": '\n'.join(text_parts) if text_parts else ""})
                    else:
                        api_messages.append({"role": "user", "content": content})
                else:
                    api_messages.append({"role": "user", "content": str(content)})
        return api_messages

    def _extract_token_stats(self, api_response: Dict) -> Dict[str, int]:
        """Извлечение статистики токенов из ответа API."""
        usage = api_response.get('usage', {})
        
        if usage:
            return {
                "prompt_tokens": usage.get('prompt_tokens', 0),
                "completion_tokens": usage.get('completion_tokens', 0),
                "total_tokens": usage.get('total_tokens', 0)
            }
        else:
            self._log("Warning: No token usage information in API response")
            return {
                "prompt_tokens": 0,
                "completion_tokens": 0,
                "total_tokens": 0
            }
    
    def get_token_stats(self) -> Dict[str, int]:
        """Возвращает текущую статистику использования токенов."""
        return {
            "session_total_tokens": self.total_tokens_used,
            "last_prompt_tokens": self.last_prompt_tokens,
            "last_completion_tokens": self.last_completion_tokens,
            "last_total_tokens": self.last_total_tokens
        }
    
    def get_context_stats(self) -> Dict[str, Any]:
        """Возвращает статистику по управлению контекстом."""
        stats = {
            "strategy": self.context_strategy,
            "total_messages": len(self.conversation_history),
            "keep_last_n": self.keep_last_n,
        }
        
        if self.context_strategy == "summary":
            stats.update({
                "num_summaries": len(self.summaries),
                "summary_interval": self.summary_interval,
                "recent_messages": min(len(self.conversation_history), self.keep_last_n),
                "summarized_messages": max(0, len(self.conversation_history) - self.keep_last_n) if self.conversation_history else 0
            })
        elif self.context_strategy == "sliding_window":
            stats.update({
                "window_size": self.keep_last_n,
                "current_window_size": len(self.conversation_history),
                "max_window_size": self.keep_last_n
            })
        elif self.context_strategy == "sticky_facts":
            stats.update({
                "num_facts": len(self.facts),
                "facts": self.facts,
                "recent_messages": len(self.conversation_history[-self.keep_last_n:]) if self.conversation_history else 0
            })
        elif self.context_strategy == "branching":
            stats.update({
                "current_branch": self.current_branch,
                "branches": list(self.branches.keys()),
                "messages_in_branch": len(self.conversation_history),
                "total_branches": len(self.branches)
            })
        
        return stats
    
    def _prepare_message_content(self, user_message: str, files: List[Dict]) -> Union[str, List[Dict]]:
        """Подготовка контента сообщения в зависимости от наличия файлов и поддержки модели."""
        if not files:
            return user_message or ""
        
        content_parts = []
        
        if user_message:
            content_parts.append({
                "type": "text",
                "text": user_message
            })
        
        for file_info in files:
            file_path = file_info.get('saved_path')
            mime_type = file_info.get('mime_type', 'application/octet-stream')
            
            if file_path and os.path.exists(file_path):
                if mime_type.startswith('image/') and self.supports_vision:
                    with open(file_path, 'rb') as img_file:
                        img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{img_base64}"
                            }
                        })
                elif mime_type.startswith('text/') or file_info.get('extracted_text'):
                    if file_info.get('extracted_text'):
                        content_parts.append({
                            "type": "text",
                            "text": f"[Файл: {file_info['filename']}]\n{file_info['extracted_text']}"
                        })
                else:
                    content_parts.append({
                        "type": "text",
                        "text": f"[Прикреплен файл: {file_info['filename']} (тип: {mime_type})]"
                    })
        
        return content_parts if len(content_parts) > 1 else content_parts[0] if content_parts else ""
    
    def _get_file_metadata(self, file_info: Dict) -> Dict:
        """Получение метаданных файла для сохранения в истории."""
        return {
            "filename": file_info.get('filename'),
            "mime_type": file_info.get('mime_type'),
            "size_bytes": file_info.get('size_bytes'),
            "saved_path": file_info.get('saved_path'),
            "preview_url": file_info.get('preview_url'),
            "extracted_text": file_info.get('extracted_text')[:500] if file_info.get('extracted_text') else None
        }

    def save_history(self, filepath: str) -> None:
        """Сохранить историю в JSON файл."""
        # Сохраняем текущую ветку
        self._save_current_branch_data()
        
        # Преобразуем пути к файлам в относительные
        branches_to_save = {}
        for branch_name, branch_data in self.branches.items():
            branch_copy = branch_data.copy()
            if "history" in branch_copy:
                history_copy = []
                for msg in branch_copy["history"]:
                    msg_copy = msg.copy()
                    if 'attachments' in msg_copy:
                        for att in msg_copy['attachments']:
                            if 'saved_path' in att and att['saved_path']:
                                att['saved_path'] = os.path.relpath(att['saved_path'], self.files_dir)
                    history_copy.append(msg_copy)
                branch_copy["history"] = history_copy
            branches_to_save[branch_name] = branch_copy
        
        full_data = {
            "version": "2.0",
            "summaries": self.summaries,
            "facts": self.facts,
            "branches": branches_to_save,
            "current_branch": self.current_branch,
            "context_strategy": self.context_strategy,
            "config": {
                "keep_last_n": self.keep_last_n,
                "summary_interval": self.summary_interval
            },
            "token_stats": {
                "total_tokens_used": self.total_tokens_used
            }
        }
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(full_data, f, ensure_ascii=False, indent=2)
        self._log(f"History saved to {filepath} (branches: {len(self.branches)})")

    def load_history(self, filepath: str) -> None:
        """Загрузить историю из JSON файла."""
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
            
            # Поддержка старого формата
            if isinstance(loaded_data, list):
                self.conversation_history = loaded_data
                self.summaries = []
                self.facts = {}
                self.branches = {"main": {"history": self.conversation_history, "facts": {}, "summaries": []}}
                self.current_branch = "main"
                self.context_strategy = "summary"
            else:
                # Новый формат
                self.summaries = loaded_data.get("summaries", [])
                self.facts = loaded_data.get("facts", {})
                self.branches = loaded_data.get("branches", {})
                self.current_branch = loaded_data.get("current_branch", "main")
                self.context_strategy = loaded_data.get("context_strategy", "summary")
                
                config = loaded_data.get("config", {})
                if config:
                    self.keep_last_n = config.get("keep_last_n", self.keep_last_n)
                    self.summary_interval = config.get("summary_interval", self.summary_interval)
                
                token_stats = loaded_data.get("token_stats", {})
                self.total_tokens_used = token_stats.get("total_tokens_used", 0)
                
                # Восстанавливаем абсолютные пути к файлам во всех ветках
                for branch_name, branch_data in self.branches.items():
                    if "history" in branch_data:
                        for msg in branch_data["history"]:
                            if 'attachments' in msg:
                                for att in msg['attachments']:
                                    if 'saved_path' in att and att['saved_path']:
                                        att['saved_path'] = os.path.abspath(os.path.join(self.files_dir, att['saved_path']))
            
            # Загружаем текущую ветку
            self._load_current_branch_data()
            
            self._log(f"History loaded from {filepath}, strategy: {self.context_strategy}, branches: {len(self.branches)}")
        else:
            self._log(f"History file {filepath} not found, starting fresh")
            self.conversation_history = []
            self.summaries = []
            self.facts = {}
            self.branches = {"main": {"history": [], "facts": {}, "summaries": []}}
            self.current_branch = "main"
            self.total_tokens_used = 0

    def get_agent_info(self) -> Dict:
        """Возвращает информацию об агенте."""
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "supports_vision": self.supports_vision,
            "history_file_path": self._history_file_path,
            "history_length": len(self.conversation_history),
            "files_dir": self.agent_files_dir,
            "max_file_size_mb": self.max_file_size_mb,
            "token_stats": self.get_token_stats(),
            "context_stats": self.get_context_stats()
        }

    @staticmethod
    def list_all_agents(history_dir: str = "agent_history") -> List[Dict]:
        """Сканирует директорию истории и возвращает информацию о всех агентах."""
        agents_info = []
        pattern = os.path.join(history_dir, "history_*.json")
        
        for filepath in glob.glob(pattern):
            filename = os.path.basename(filepath)
            parts = filename.replace('history_', '').replace('.json', '').split('_')
            if len(parts) >= 2:
                agent_id = parts[0]
                model = '_'.join(parts[1:])
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        loaded_data = json.load(f)
                        if isinstance(loaded_data, list):
                            history = loaded_data
                            strategy = "summary"
                        else:
                            history = loaded_data.get("branches", {}).get(loaded_data.get("current_branch", "main"), {}).get("history", [])
                            strategy = loaded_data.get("context_strategy", "summary")
                        history_length = len(history)
                except Exception:
                    history_length = 0
                
                agents_info.append({
                    "filename": filename,
                    "agent_id": agent_id,
                    "model": model,
                    "history_file_path": filepath,
                    "history_length": history_length,
                    "strategy": strategy
                })
        
        return agents_info

    def change_agent_id(self, new_agent_id: str) -> None:
        """Изменяет ID агента и переименовывает файлы."""
        if not new_agent_id or not new_agent_id.strip():
            raise ValueError("new_agent_id cannot be empty")
        
        new_agent_id = new_agent_id.strip()
        old_filepath = self._history_file_path
        old_agent_id = self.agent_id
        
        new_agent_files_dir = os.path.join(self.files_dir, new_agent_id)
        if os.path.exists(self.agent_files_dir) and self.agent_files_dir != new_agent_files_dir:
            os.rename(self.agent_files_dir, new_agent_files_dir)
            self.agent_files_dir = new_agent_files_dir
        
        self.agent_id = new_agent_id
        
        safe_model = self._sanitize_filename(self.model)
        safe_new_agent_id = self._sanitize_filename(self.agent_id)
        new_filename = f"history_{safe_new_agent_id}_{safe_model}.json"
        new_filepath = os.path.join(self.history_dir, new_filename)
        
        if os.path.exists(old_filepath) and old_filepath != new_filepath:
            os.rename(old_filepath, new_filepath)
        
        self._history_file_path = new_filepath
        
        if old_filepath == new_filepath:
            self._save_to_default_file()
        
        self._log(f"Changed agent ID from {old_agent_id} to {self.agent_id}")