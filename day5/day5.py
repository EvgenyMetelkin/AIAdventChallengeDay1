import os
from openai import OpenAI
from openai import OpenAIError
from datetime import datetime
import time
from openai.types.chat import ChatCompletion

client = OpenAI(
    api_key=os.environ["PROXYAPI_KEY"],
    base_url= "https://openai.api.proxyapi.ru/v1",
)

now = datetime.now().strftime("%H:%M:%S")

# model = "openai/gpt-5.4-pro-2026-03-05"
# model = "openai/gpt-5.4-2026-03-05"  
# model = "openai/gpt-5.4-mini-2026-03-17"
# model = "openai/gpt-5.4-nano-2026-03-17"

# model = "gemini/gemini-2.5-pro"
# model = "gemini/gemini-2.5-flash"
# model = "gemini/gemini-3.1-flash-lite"


question = ("Напиши оптимальное решение задачи Two Sum на Python."
"Условие:"
"Дан массив целых чисел nums и целевое число target."
"Найди два индекса i и j, таких что nums[i] + nums[j] == target."
"Предположи, что каждый вход имеет ровно одно решение, и ты не можешь использовать один и тот же элемент дважды."
"Требования:"
"1. Напиши решение с временной сложностью O(n)"
"2. Объясни, почему твой алгоритм имеет сложность O(n)"
"3. Проанализируй временную и пространственную сложность"
"4. Добавь комментарии к коду"
"5. Приведи пример использования с тестовым случаем"
"Пример:"
"Вход: nums = [2, 7, 11, 15], target = 19"
"Выход: [0, 1] (потому что nums[0] + nums[1] = 2 + 7 = 19)")


def get_chat_completion(user_message: str, model: str, system: str = "") -> ChatCompletion:
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
        timeout=150.0,
    )
    return chat_completion
        
        
def completion_and_save(model, user_message: str, system: str = "") -> str:
    start_time = time.time()
    chat_completion = get_chat_completion(user_message = user_message, system = system, model = model)
    message = chat_completion.choices[0].message.content
    completion_tokens = chat_completion.usage.completion_tokens
    prompt_tokens = chat_completion.usage.prompt_tokens
    total_tokens = chat_completion.usage.total_tokens
    
    finish_time = time.time()
    duration_ms = (finish_time - start_time) * 1000

    with open("day5/" + model + ".txt", "w", encoding="utf-8") as f:
        f.write("start_time:\n" + now + 
                "\nduration_ms:\n" + str(duration_ms) + 
                "\nNumber of tokens in the generated completion:\n" + str(completion_tokens) + 
                "\nNumber of tokens in the prompt:\n" + str(prompt_tokens) + 
                "\nTotal number of tokens used in the request (prompt + completion):\n" + str(total_tokens) + 
                "\nuser_message:\n" + user_message + 
                "\nresult:\n" + message)
        
    print("\nWriten: " + model + ".txt")

    return message

if __name__ == "__main__":
    try:
        completion_and_save("openai/gpt-5.4-pro-2026-03-05", question)
        completion_and_save("openai/gpt-5.4-2026-03-05", question)
        completion_and_save("openai/gpt-5.4-mini-2026-03-17", question)
        completion_and_save("openai/gpt-5.4-nano-2026-03-17", question)
        
        completion_and_save("gemini/gemini-3.1-pro-preview", question)
        completion_and_save("gemini/gemini-3.5-flash", question)
        completion_and_save("gemini/gemini-3.1-flash-lite", question)
        completion_and_save("gemini/gemini-2.5-pro", question)
        completion_and_save("gemini/gemini-2.5-flash", question)
        completion_and_save("gemini/gemini-2.5-flash-lite", question)
        
        
        print("\n" + now + "\n!!!!DONE!!!!\n\n")

    except OpenAIError as e:
        print(f"Ошибка API OpenAI: {e}")
    except KeyError as e:
        print(f"Ошибка доступа к переменной окружения: {e}")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")