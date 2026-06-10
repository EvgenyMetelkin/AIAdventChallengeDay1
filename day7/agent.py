import json
import os
import logging
import uuid
import glob
from typing import List, Dict, Optional
import httpx

class Agent:
    """Агент для взаимодействия с LLM через OpenAI‑совместимый API."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-3.5-turbo", temperature: float = 0.7,
                 max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False,
                 agent_id: Optional[str] = None, history_dir: str = "agent_history"):
        self.api_key = api_key
        self.base_url = base_url.rstrip('/')
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.verbose = verbose
        self.history_dir = history_dir
        
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
        
        # Создание директории для истории, если её нет
        os.makedirs(self.history_dir, exist_ok=True)
        
        # Формирование пути к файлу истории
        safe_model = self._sanitize_filename(self.model)
        safe_agent_id = self._sanitize_filename(self.agent_id)
        history_filename = f"history_{safe_agent_id}_{safe_model}.json"
        self._history_file_path = os.path.join(self.history_dir, history_filename)
        
        self.conversation_history: List[Dict[str, str]] = []
        
        # Настройка логгирования
        if verbose:
            logging.basicConfig(level=logging.INFO)
            self.logger = logging.getLogger(__name__)
        else:
            self.logger = None
        
        # Автоматическая загрузка истории, если файл существует
        if os.path.exists(self._history_file_path):
            self.load_history(self._history_file_path)
            self._log(f"Loaded history for agent {self.agent_id} from {self._history_file_path}")
        else:
            self._log(f"No existing history found for agent {self.agent_id}, starting fresh")
            self.conversation_history = []

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
        self._log(f"Saved history for agent {self.agent_id} to {self._history_file_path}")

    def reset_conversation(self) -> None:
        """Сброс истории диалога с очисткой JSON файла."""
        self.conversation_history = []
        self._save_to_default_file()
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
        
        # Автоматическое сохранение после изменения истории
        self._save_to_default_file()

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
            # Синхронизация с дефолтным файлом после загрузки
            self._save_to_default_file()
        else:
            self._log(f"History file {filepath} not found, starting fresh")
            self.conversation_history = []

    def get_agent_info(self) -> Dict:
        """Возвращает информацию об агенте."""
        return {
            "agent_id": self.agent_id,
            "model": self.model,
            "history_file_path": self._history_file_path,
            "history_length": len(self.conversation_history)
        }

    @staticmethod
    def list_all_agents(history_dir: str = "agent_history") -> List[Dict]:
        """Сканирует директорию истории и возвращает информацию о всех агентах."""
        agents_info = []
        pattern = os.path.join(history_dir, "history_*.json")
        
        for filepath in glob.glob(pattern):
            filename = os.path.basename(filepath)
            # Извлекаем agent_id и модель из имени файла
            # Формат: history_{agent_id}_{model}.json
            parts = filename.replace('history_', '').replace('.json', '').split('_')
            if len(parts) >= 2:
                # Предполагаем, что agent_id это первая часть, а всё остальное - модель
                agent_id = parts[0]
                model = '_'.join(parts[1:])
                
                # Получаем размер истории
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        history = json.load(f)
                        history_length = len(history)
                except Exception:
                    history_length = 0
                
                agents_info.append({
                    "filename": filename,
                    "agent_id": agent_id,
                    "model": model,
                    "history_file_path": filepath,
                    "history_length": history_length
                })
        
        return agents_info

    def change_agent_id(self, new_agent_id: str) -> None:
        """Изменяет ID агента и переименовывает файл истории."""
        if not new_agent_id or not new_agent_id.strip():
            raise ValueError("new_agent_id cannot be empty")
        
        # Очищаем новый ID от недопустимых символов
        new_agent_id = new_agent_id.strip()
        
        # Сохраняем старый путь
        old_filepath = self._history_file_path
        old_agent_id = self.agent_id
        
        # Обновляем ID
        self.agent_id = new_agent_id
        
        # Формируем новый путь к файлу
        safe_model = self._sanitize_filename(self.model)
        safe_new_agent_id = self._sanitize_filename(self.agent_id)
        new_filename = f"history_{safe_new_agent_id}_{safe_model}.json"
        new_filepath = os.path.join(self.history_dir, new_filename)
        
        # Переименовываем файл, если он существует
        if os.path.exists(old_filepath) and old_filepath != new_filepath:
            os.rename(old_filepath, new_filepath)
            self._log(f"Renamed history file from {old_filepath} to {new_filepath}")
        
        # Обновляем путь к файлу
        self._history_file_path = new_filepath
        
        # Сохраняем текущую историю в новый файл (если файл не был просто переименован)
        if old_filepath == new_filepath:
            self._save_to_default_file()
        
        self._log(f"Changed agent ID from {old_agent_id} to {self.agent_id}")