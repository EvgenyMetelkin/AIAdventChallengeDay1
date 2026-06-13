# LLM Веб-интерфейс Agent

Асинхронный агент для взаимодействия с OpenAI‑совместимыми LLM API с веб‑чатом.  
Поддерживает историю диалога, несколько независимых сессий, сброс контекста.

## Требования

- Python 3.9+
- Установленные зависимости из `requirements.txt`

## Установка

1. Клонируйте репозиторий (или скопируйте файлы).
2. Создайте виртуальное окружение:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/Mac
   venv\Scripts\activate     # Windows

uvicorn web:app --reload --host 0.0.0.0 --port 8000
