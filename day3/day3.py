import os
from openai import OpenAI
from openai import OpenAIError
from datetime import datetime

client = OpenAI(
    api_key=os.environ["PROXYAPI_KEY"],
    base_url="https://openai.api.proxyapi.ru/v1",
)

model = "openai/gpt-5.4-nano-2026-03-17"

now = datetime.now().strftime("%H:%M:%S")

question = ("Выведи правильный ответ на задачу. Дан массив целых чисел, нужно:"
" найти все подпоследовательности подряд, сумма которых равна заданному числу S;"
" среди них выбрать самую короткую;"
" если таких несколько — вывести ту, которая начинается раньше."
" [12, -7, 4, -4, 3, -6, 10, -5, 1, 8, -2, 4, -9, 6, 3, -1, 2, -7, 11, -4, 5, -3, 2, 9, -8, 4, -1, 6, -5, 3, 7, -2, 1, 9, -3, 6, -8, 5, 2, -1, 7, -6, 8, -3, 4, 2, -9, 5, -1, 10]"
" S = 17")

# [9, -3, 6, -8, 5, 2, -1, 7]

def get_chat_completion(user_message: str, system: str = "", max_tokens: int = 5000) -> str:
    system_prompt = "Будь краток" if system == "" else system

    chat_completion = client.chat.completions.create(
        model = model,
        messages=[
            {
                "role": "system",
                "content": system_prompt
            },
            {
                "role": "user",
                "content": user_message
            }
        ],
        max_completion_tokens = max_tokens,
        timeout=30.0,
 )
    return chat_completion.choices[0].message.content
        
        
def completion_and_save(filename, user_message: str, system: str = "", max_tokens: int = 5000) -> str:
    result = get_chat_completion(user_message, system, max_tokens)
    
    with open("day3/" + filename, "w", encoding="utf-8") as f:
        f.write(now + "\n\nuser_message:\n" + user_message + "\n\nsystem:\n" + system + "\n\nresult:\n" + result)
        
    print("\nWriten: " + filename)

    return result
        

if __name__ == "__main__":
    try:
        completion_and_save("result1.txt", question)
        
        completion_and_save("result2.txt", "Решай пошагово:\n" + question)
        completion_and_save("result2.1.txt", user_message = question, system = "Решай пошагово.")
        
        pre_promt_3 = "В одинарных ковычках задача, составь к ней промт чтобы решение было максимально точным, добавь пункты по которым нужно получить решение \'" + question +"\'"
        promt_3 = get_chat_completion(pre_promt_3, system="Без рассуждений")
        completion_and_save("result3.txt", user_message = promt_3)

        pre_promt_4 = "Составь промт с группой экспертов: аналитик, инженер, критик. Опиши какие действия от них ожидаются. Задача: \'" + question +"\'"
        promt_4 = get_chat_completion(pre_promt_4, system="Без рассуждений")
        completion_and_save("result4.txt", user_message = promt_4)
        
        print("\n" + now + "\n!!!!DONE!!!!\n\n")

    except OpenAIError as e:
        print(f"Ошибка API OpenAI: {e}")
    except KeyError as e:
        print(f"Ошибка доступа к переменной окружения: {e}")
    except Exception as e:
        print(f"Неожиданная ошибка: {e}")