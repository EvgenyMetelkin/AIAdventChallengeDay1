import json
import os
import logging
import uuid
import glob
from typing import List, Dict, Optional
import httpx
from user import User

class Agent:
    """Агент для взаимодействия с LLM через OpenAI‑совместимый API."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-3.5-turbo", temperature: float = 0.7,
                 max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False,
                 agent_id: Optional[str] = None, history_dir: str = "agent_history",
                 user: Optional[User] = None):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.verbose = verbose
        self.history_dir = history_dir
        self.user = user  # Текущий пользователь
        
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
        
        # Настройка логгирования
        if verbose:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = None
        
        self._log(f"Agent initialized with user: {user.name if user else 'None'}")

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger.info(msg)
        elif self.verbose:
            print(f"[LOG] {msg}")

    def set_user(self, user: User) -> None:
        """Установка текущего пользователя."""
        self.user = user
        self._log(f"Switched to user: {user.name} ({user.user_id})")

    def reset_conversation(self) -> None:
        """Сброс истории диалога текущего пользователя."""
        if self.user:
            self.user.reset_history()
            self._log(f"Conversation history reset for user {self.user.name}")
        else:
            raise Exception("No user selected")

    async def send_message(self, user_message: str) -> str:
        """Отправить сообщение LLM, получить ответ (с сохранением истории)."""
        if not self.user:
            raise Exception("No user selected. Please select a user first.")
        
        # Добавляем сообщение пользователя в историю
        self.user.history.append({"role": "user", "content": user_message})
        
        # Формируем messages для запроса
        messages = []
        
        # Добавляем system промпт из предпочтений
        system_prompt = self.user.get_system_prompt()
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        
        # Добавляем историю
        messages.extend(self.user.history)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        self._log(f"Request to {url} with model {self.model}, history length {len(self.user.history)}")

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

        # Добавляем ответ ассистента в историю
        self.user.history.append({"role": "assistant", "content": assistant_message})
        
        # Сохраняем историю
        self.user.save_history()

        if self.verbose and 'usage' in data:
            usage = data['usage']
            self._log(f"Token usage: prompt {usage.get('prompt_tokens',0)}, "
                      f"completion {usage.get('completion_tokens',0)}, total {usage.get('total_tokens',0)}")

        return assistant_message

    def get_agent_info(self) -> Dict:
        """Возвращает информацию об агенте."""
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "user": self.user.to_dict() if self.user else None,
            "has_user": bool(self.user)
        }