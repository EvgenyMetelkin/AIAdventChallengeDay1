import os
from openai import OpenAI
from openai import OpenAIError

client = OpenAI(
    api_key=os.environ["PROXYAPI_KEY"],
    base_url="https://openai.api.proxyapi.ru/v1",
)

model = "openai/gpt-4.1-mini-2025-04-14"

def get_chat_completion(user_message: str) -> str:
    chat_completion = client.chat.completions.create(
        model = model,
        messages=[
            {
                "role": "user",
                "content": user_message,
                
            },
        ],
        timeout=30.0,
    )
    return chat_completion.choices[0].message.content

def get_chat_completion_with_params(user_message: str, max_tokens: int) -> str:
    chat_completion = client.chat.completions.create(
        model = model,
        messages=[
            {
                "role": "system",
                "content": (
                    "Отвечай строго в формате JSON.\n"
                    "Формат ответа: {\"answer\": string, \"confidence\": number}.\n"
                    "Ограничение длины: не более 120 слов.\n"
                    "Заверши ответ сразу после закрывающей фигурной скобки.\n"
                    "Не добавляй лишний текст, пояснения или markdown."
                )
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        max_completion_tokens = max_tokens,
        stop=["\n\n", "END_JSON"],
        timeout=30.0,
 )
    return chat_completion.choices[0].message.content


if __name__ == "__main__":
    try:
        result1 = get_chat_completion("Объясни, что такое аннотированная ссылка.")
        result2 = get_chat_completion_with_params("Объясни, что такое аннотированная ссылка.", max_tokens = 100)

        print(result1 + "\n\n")
        print(result2 + "\n\n")
        
        finishRequest = "Сравни ответы двух запросов к LLM. \n\nОтвет 1: " + result1 + "\n\n Ответ 2: " + result2
        
        print(finishRequest + "\n\n")

        finishResult = get_chat_completion(finishRequest)
        
        print(finishResult + "\n\n")

    except OpenAIError as e:
        print(f"Ошибка API OpenAI: {e}")
    except KeyError as e:
        print(f"Ошибка доступа к переменной окружения: {e}")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")