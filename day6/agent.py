import json
import os
import logging
from typing import List, Dict, Optional
import httpx

class Agent:
    """Агент для взаимодействия с LLM через OpenAI‑совместимый API."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-3.5-turbo", temperature: float = 0.7,
                 max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.verbose = verbose
        self.conversation_history: List[Dict[str, str]] = []

        if verbose:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = None

    def _log(self, msg: str) -> None:
        if self.logger:
            self.logger.info(msg)

    def reset_conversation(self) -> None:
        """Сброс истории диалога."""
        self.conversation_history = []
        self._log("Conversation history reset.")

    async def send_message(self, user_message: str) -> str:
        """Отправить сообщение LLM, получить ответ (с сохранением истории)."""
        self.conversation_history.append({"role": "user", "content": user_message})

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        payload = {
            "model": self.model,
            "messages": self.conversation_history,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        self._log(f"Request to {url} with model {self.model}, history length {len(self.conversation_history)}")

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

        self.conversation_history.append({"role": "assistant", "content": assistant_message})

        if self.verbose and 'usage' in data:
            usage = data['usage']
            self._log(f"Token usage: prompt {usage.get('prompt_tokens',0)}, "
                      f"completion {usage.get('completion_tokens',0)}, total {usage.get('total_tokens',0)}")

        return assistant_message

    def save_history(self, filepath: str) -> None:
        """Сохранить историю в JSON файл."""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(self.conversation_history, f, ensure_ascii=False, indent=2)
        self._log(f"History saved to {filepath}")

    def load_history(self, filepath: str) -> None:
        """Загрузить историю из JSON файла (если существует)."""
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                self.conversation_history = json.load(f)
            self._log(f"History loaded from {filepath}")
        else:
            self._log(f"History file {filepath} not found, starting fresh")