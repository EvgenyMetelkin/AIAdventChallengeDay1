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

--verbose (-v) – подробное логирование (URL, токены)

--history-file <file.json> – сохранять/загружать историю в JSON‑файл

--api-key, --model, --temperature и т.д. – переопределение параметров

Пример с историей и логированием:
python cli.py --history-file conv.json --verbose