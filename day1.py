import os
import anthropic

client = anthropic.Anthropic(
    api_key=os.environ["PROXYAPI_KEY"],
    base_url="https://api.proxyapi.ru/anthropic",
)

message = client.messages.create(
    model="claude-haiku-4-5-20251001",
    max_tokens=10000,
    messages=[
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": "Напишите минимальный python код, который: отправляет запрос в LLM через API, получает ответ, выводит его в консоль или простой интерфейс (CLI / Web)"
                }
            ]
        }
    ]
)

print(message.content[0].text)

# import os
# from openai import OpenAI

# client = OpenAI(
#     api_key=os.environ["PROXYAPI_KEY"],
#     base_url="https://openai.api.proxyapi.ru/v1",
# )

# chat_completion = client.chat.completions.create(
#     model="anthropic/claude-sonnet-4-20250514", 
#     messages=[
#         {
#             "role": "user",
#             "content": "Привет!"
#         }
#     ]
# )

# print(chat_completion.choices[0].message.content)