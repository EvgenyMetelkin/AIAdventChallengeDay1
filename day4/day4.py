import os
from openai import OpenAI
from openai import OpenAIError
from datetime import datetime

client = OpenAI(
    api_key=os.environ["PROXYAPI_KEY"],
    base_url= "https://openai.api.proxyapi.ru/v1",
)

# model = "openai/gpt-5.4-pro-2026-03-05"
# model = "openai/gpt-5.4-2026-03-05"  
# model = "openai/gpt-5.4-mini-2026-03-17"
# model = "openai/gpt-5.4-nano-2026-03-17"

# model = "gemini/gemini-2.5-pro"
# model = "gemini/gemini-2.5-flash"
model = "gemini/gemini-3.1-flash-lite"

now = datetime.now().strftime("%H:%M:%S")

# question = ("Что думаешь по поводу цифры 4? "
#             "Напиши стих. "
#             "Придумай анекдот. ")

question = "Придумай 10 необычных, но правдоподобных слоганов для кофейни в стиле минимализм, каждый — в разном тоне: спокойный, дерзкий, уютный, премиальный, ироничный."


def get_chat_completion(user_message: str, system: str = "", max_tokens: int = 5000, temperature: float = 1.0) -> str:
    chat_completion = client.chat.completions.create(
        model = model,
        messages=[
            {
                "role": "system",
                "content": system
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        max_completion_tokens = max_tokens,
        timeout=30.0,
        temperature=temperature,
    )
    return chat_completion.choices[0].message.content
        
        
def completion_and_save(filename, user_message: str, system: str = "", max_tokens: int = 5000, temperature: float = 1.0) -> str:
    result = get_chat_completion(user_message = user_message, system = system, max_tokens = max_tokens, temperature = temperature)
    
    with open("day4/" + filename, "w", encoding="utf-8") as f:
        f.write(now + "\nuser_message:\n" + user_message + "\nsystem:\n" + system + "\ntemperature:\n" + str(temperature) + "\nresult:\n" + result)
        
    print("\nWriten: " + filename)

    return result
        

if __name__ == "__main__":
    try:
        completion_and_save(model + "-temperature-0.0.txt", question, temperature = 0.0)
        completion_and_save(model + "-temperature-0.7.txt", question, temperature = 0.7)
        completion_and_save(model + "-temperature-1.2.txt", question, temperature = 1.2)
        # completion_and_save(model + "-temperature-2.0.txt", question, temperature = 2.0)
        
        print("\n" + now + "\n!!!!DONE!!!!\n\n")

    except OpenAIError as e:
        print(f"Ошибка API OpenAI: {e}")
    except KeyError as e:
        print(f"Ошибка доступа к переменной окружения: {e}")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")