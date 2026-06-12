import json
import os
import logging
import uuid
import glob
import base64
from typing import List, Dict, Optional, Any, Union, Tuple
import httpx
from pathlib import Path

class Agent:
    """Агент для взаимодействия с LLM через OpenAI‑совместимый API с поддержкой файлов."""

    def __init__(self, api_key: str, base_url: str = "https://api.openai.com/v1",
                 model: str = "gpt-3.5-turbo", temperature: float = 0.7,
                 max_tokens: int = 500, timeout: float = 30.0, verbose: bool = False,
                 agent_id: Optional[str] = None, history_dir: str = "agent_history",
                 files_dir: str = "agent_files", max_file_size_mb: int = 10):
        # Настройка логгирования (должна быть первой!)
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
        
        self.conversation_history: List[Dict[str, Any]] = []
        
        # Определение поддержки vision моделью
        self.supports_vision = any(x in model.lower() for x in ['vision', 'gpt-4', 'gpt-4o', 'claude-3'])
        
        # Автоматическая загрузка истории
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

    def reset_conversation(self) -> None:
        """Сброс истории диалога с очисткой JSON файла и обнулением статистики токенов."""
        # Очищаем файлы агента
        import shutil
        if os.path.exists(self.agent_files_dir):
            shutil.rmtree(self.agent_files_dir)
            os.makedirs(self.agent_files_dir, exist_ok=True)
        
        self.conversation_history = []
        
        # Обнуляем статистику токенов
        self.total_tokens_used = 0
        self.last_prompt_tokens = 0
        self.last_completion_tokens = 0
        self.last_total_tokens = 0
        
        self._save_to_default_file()
        self._log("Conversation history reset and files cleared. Token stats reset.")

    async def send_message(self, user_message: str = "", files: Optional[List[Dict]] = None) -> Tuple[str, Dict[str, int]]:
        """Отправить сообщение LLM, получить ответ с статистикой токенов (с сохранением истории)."""
        if files is None:
            files = []
        
        # Подготовка контента сообщения
        content = self._prepare_message_content(user_message, files)
        
        # Сохраняем сообщение пользователя в истории с метаданными о файлах
        user_message_obj = {
            "role": "user",
            "content": content,
            "attachments": [self._get_file_metadata(f) for f in files] if files else [],
            "tokens": None  # у user нет токенов
        }
        self.conversation_history.append(user_message_obj)

        url = f"{self.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        
        # Подготовка payload для API
        api_messages = self._prepare_api_messages()
        payload = {
            "model": self.model,
            "messages": api_messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens
        }

        self._log(f"Request to {url} with model {self.model}, history length {len(self.conversation_history)}")
        if files:
            self._log(f"Sending {len(files)} file(s) in message")

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

        # Извлечение статистики токенов из ответа API
        token_stats = self._extract_token_stats(data)
        
        # Обновляем общую статистику
        self.total_tokens_used += token_stats.get("total_tokens", 0)
        self.last_prompt_tokens = token_stats.get("prompt_tokens", 0)
        self.last_completion_tokens = token_stats.get("completion_tokens", 0)
        self.last_total_tokens = token_stats.get("total_tokens", 0)

        # Сохраняем сообщение ассистента с статистикой токенов
        assistant_message_obj = {
            "role": "assistant",
            "content": assistant_message,
            "tokens": token_stats
        }
        self.conversation_history.append(assistant_message_obj)
        
        # Автоматическое сохранение после изменения истории
        self._save_to_default_file()

        if self.verbose and 'usage' in data:
            usage = data['usage']
            self._log(f"Token usage: prompt {usage.get('prompt_tokens',0)}, "
                      f"completion {usage.get('completion_tokens',0)}, total {usage.get('total_tokens',0)}")
            self._log(f"Session total tokens: {self.total_tokens_used}")

        # Возвращаем ответ и статистику
        return assistant_message, self.get_token_stats()

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
            # Если API не вернул статистику
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
    
    def _prepare_message_content(self, user_message: str, files: List[Dict]) -> Union[str, List[Dict]]:
        """Подготовка контента сообщения в зависимости от наличия файлов и поддержки модели."""
        if not files:
            return user_message or ""
        
        # Если есть файлы, готовим мультимодальный контент
        content_parts = []
        
        # Добавляем текст
        if user_message:
            content_parts.append({
                "type": "text",
                "text": user_message
            })
        
        # Добавляем файлы
        for file_info in files:
            file_path = file_info.get('saved_path')
            mime_type = file_info.get('mime_type', 'application/octet-stream')
            
            if file_path and os.path.exists(file_path):
                if mime_type.startswith('image/') and self.supports_vision:
                    # Для изображений используем base64 (если модель поддерживает vision)
                    with open(file_path, 'rb') as img_file:
                        img_base64 = base64.b64encode(img_file.read()).decode('utf-8')
                        content_parts.append({
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:{mime_type};base64,{img_base64}"
                            }
                        })
                elif mime_type.startswith('text/') or file_info.get('extracted_text'):
                    # Для текстовых файлов добавляем извлеченный текст
                    if file_info.get('extracted_text'):
                        content_parts.append({
                            "type": "text",
                            "text": f"[Файл: {file_info['filename']}]\n{file_info['extracted_text']}"
                        })
                else:
                    # Для неподдерживаемых типов - просто упоминание
                    content_parts.append({
                        "type": "text",
                        "text": f"[Прикреплен файл: {file_info['filename']} (тип: {mime_type})]"
                    })
        
        return content_parts if len(content_parts) > 1 else content_parts[0] if content_parts else ""
    
    def _prepare_api_messages(self) -> List[Dict]:
        """Подготовка сообщений для API OpenAI."""
        api_messages = []
        
        for msg in self.conversation_history:
            if msg['role'] == 'assistant':
                api_messages.append({"role": "assistant", "content": msg['content']})
            else:
                # Для пользовательских сообщений
                content = msg['content']
                
                # Если content - строка, используем как есть
                if isinstance(content, str):
                    api_messages.append({"role": "user", "content": content})
                # Если content - список (мультимодальный)
                elif isinstance(content, list):
                    # Если модель не поддерживает vision, извлекаем только текст
                    if not self.supports_vision:
                        # Извлекаем текст из всех частей, где есть поле 'text'
                        text_parts = []
                        for part in content:
                            if isinstance(part, dict) and part.get('type') == 'text':
                                text_parts.append(part.get('text', ''))
                        text_content = '\n'.join(text_parts) if text_parts else "[Файлы прикреплены]"
                        api_messages.append({"role": "user", "content": text_content})
                    else:
                        api_messages.append({"role": "user", "content": content})
                else:
                    # Fallback для других типов
                    api_messages.append({"role": "user", "content": str(content)})
        
        return api_messages
    
    def _get_file_metadata(self, file_info: Dict) -> Dict:
        """Получение метаданных файла для сохранения в истории."""
        return {
            "filename": file_info.get('filename'),
            "mime_type": file_info.get('mime_type'),
            "size_bytes": file_info.get('size_bytes'),
            "saved_path": file_info.get('saved_path'),
            "preview_url": file_info.get('preview_url'),
            "extracted_text": file_info.get('extracted_text')[:500] if file_info.get('extracted_text') else None  # Ограничиваем длину
        }

    def save_history(self, filepath: str) -> None:
        """Сохранить историю в JSON файл (включая статистику токенов)."""
        # Для сохранения преобразуем пути к файлам в относительные
        history_to_save = []
        for msg in self.conversation_history:
            msg_copy = msg.copy()
            if 'attachments' in msg_copy:
                for att in msg_copy['attachments']:
                    if 'saved_path' in att and att['saved_path']:
                        # Сохраняем относительный путь
                        att['saved_path'] = os.path.relpath(att['saved_path'], self.files_dir)
            # Убеждаемся, что поле tokens сохраняется
            if 'tokens' not in msg_copy:
                msg_copy['tokens'] = None
            history_to_save.append(msg_copy)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(history_to_save, f, ensure_ascii=False, indent=2)
        self._log(f"History saved to {filepath}")

    def load_history(self, filepath: str) -> None:
        """Загрузить историю из JSON файла (если существует) с восстановлением статистики токенов."""
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                loaded_history = json.load(f)
            
            # Восстанавливаем абсолютные пути к файлам
            for msg in loaded_history:
                if 'attachments' in msg:
                    for att in msg['attachments']:
                        if 'saved_path' in att and att['saved_path']:
                            att['saved_path'] = os.path.abspath(os.path.join(self.files_dir, att['saved_path']))
                # Обеспечиваем наличие поля tokens для старых сохранений
                if 'tokens' not in msg:
                    msg['tokens'] = None
            
            self.conversation_history = loaded_history
            
            # Восстанавливаем общую статистику токенов из истории
            self.total_tokens_used = 0
            for msg in self.conversation_history:
                if msg['role'] == 'assistant' and msg.get('tokens'):
                    tokens = msg['tokens']
                    if isinstance(tokens, dict):
                        self.total_tokens_used += tokens.get('total_tokens', 0)
            
            self._log(f"History loaded from {filepath}, restored token stats: {self.total_tokens_used} total tokens")
            self._save_to_default_file()
        else:
            self._log(f"History file {filepath} not found, starting fresh")
            self.conversation_history = []
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
            "token_stats": self.get_token_stats()  # Добавляем статистику токенов
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
                        history = json.load(f)
                        history_length = len(history)
                        # Подсчет токенов
                        total_tokens = 0
                        for msg in history:
                            if msg.get('role') == 'assistant' and msg.get('tokens'):
                                tokens = msg['tokens']
                                if isinstance(tokens, dict):
                                    total_tokens += tokens.get('total_tokens', 0)
                except Exception:
                    history_length = 0
                    total_tokens = 0
                
                agents_info.append({
                    "filename": filename,
                    "agent_id": agent_id,
                    "model": model,
                    "history_file_path": filepath,
                    "history_length": history_length,
                    "total_tokens": total_tokens
                })
        
        return agents_info

    def change_agent_id(self, new_agent_id: str) -> None:
        """Изменяет ID агента и переименовывает файлы."""
        if not new_agent_id or not new_agent_id.strip():
            raise ValueError("new_agent_id cannot be empty")
        
        new_agent_id = new_agent_id.strip()
        old_filepath = self._history_file_path
        old_agent_id = self.agent_id
        
        # Перемещаем файлы агента
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