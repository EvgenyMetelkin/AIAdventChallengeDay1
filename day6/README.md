# LLM CLI Agent

Консольное приложение для взаимодействия с LLM (OpenAI‑совместимый API) с поддержкой истории диалога.

## Установка

1. Клонируйте или распакуйте архив.
2. Создайте виртуальное окружение (Python 3.9+):
   ```bash
   python -m venv venv
   source venv/bin/activate   # Linux/Mac
   venv\Scripts\activate      # Windows

--verbose (-v) – подробное логирование (URL, токены)

--history-file <file.json> – сохранять/загружать историю в JSON‑файл

--api-key, --model, --temperature и т.д. – переопределение параметров

Пример с историей и логированием:
python cli.py --history-file conv.json --verbose