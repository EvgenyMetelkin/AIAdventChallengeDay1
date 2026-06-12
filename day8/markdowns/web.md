Класс Agent (интерфейс использования в app.py)
Обзор
Класс для управления диалогом с LLM. Используется в FastAPI‑приложении для обработки сообщений, хранения истории и сохранения диалогов на диск.

Зависимости
Импортируется из локального модуля agent.py. Использует asyncio для асинхронных вызовов.

Публичные методы
Метод	Параметры	Возвращает	Описание
send_message	message: str	str (async)	Отправить сообщение, получить ответ. Обновляет conversation_history.
reset_conversation	нет	None	Очищает историю и удаляет файл на диске.
get_agent_info	нет	Dict	Возвращает метаданные: agent_id, model, temperature, max_tokens, history_length.
Поля
Поле	Тип	Описание
conversation_history	List[Dict]	Список сообщений вида [{"role": "user/assistant", "content": "..."}]
agent_id	str	Уникальный ID для файла истории
Конструктор
python
Agent(
    api_key: str,
    base_url: Optional[str],
    model: str,
    temperature: float,
    max_tokens: int,
    verbose: bool,
    agent_id: str,
    history_dir: str
)
Пример использования (из app.py)
python
agent = Agent(
    api_key=LLM_API_KEY,
    base_url=LLM_BASE_URL,
    model=LLM_MODEL,
    temperature=TEMPERATURE,
    max_tokens=MAX_TOKENS,
    verbose=VERBOSE,
    agent_id="1",
    history_dir=HISTORY_DIR
)

reply = await agent.send_message("Привет")
agent.reset_conversation()
info = agent.get_agent_info()
Жизненный цикл в приложении
Создаётся один раз при старте FastAPI (в lifespan).

Используется в эндпоинтах /send, /reset, /history, /info.

Автоматически сохраняет историю после каждого сообщения.

Не требует явного закрытия — данные уже на диске.

Диаграмма последовательности (вызов /send)
sequenceDiagram
    participant Client
    participant FastAPI as app.post(/send)
    participant Agent
    participant LLM_API as OpenAI API
    participant FileSystem

    Client->>FastAPI: POST /send {"message": "Hi"}
    FastAPI->>Agent: await agent.send_message("Hi")
    Agent->>Agent: добавить user-сообщение в историю
    Agent->>LLM_API: запрос с полной историей
    LLM_API-->>Agent: ответ ассистента
    Agent->>Agent: добавить assistant-сообщение
    Agent->>FileSystem: сохранить историю в JSON
    Agent-->>FastAPI: вернуть reply
    FastAPI-->>Client: {"assistant_reply": "...", "history": [...]}