# Please install OpenAI SDK first: `pip3 install openai`
import os
from dotenv import load_dotenv
from openai import OpenAI

# ==============================================
# ENV CONFIG
# ==============================================

load_dotenv()

client = OpenAI(
    api_key=os.environ.get('DEEPSEEK_API_KEY'),
    base_url="https://api.deepseek.com")

# ==============================================
# CONVO
# ==============================================

def print_header(): 
    print() 
    print("╭──────────────────────────────────────────────────────────╮") 
    print("│                                                          │") 
    print("│                      DEEPSEEK CHAT                       │") 
    print("│                  Terminal AI Assistant                   │")
    print("│                                                          │") 
    print("╰──────────────────────────────────────────────────────────╯") 
    print(" Press Ctrl+C to exit the chat or type 'exit', 'quit', or 'q' to quit.") 
    print("────────────────────────────────────────────────────────────") 
    print()

print_header()

messages = [
    {"role": "system", "content": "You are a helpful assistant"},
]

while True:
    try:
        user_input = input("You\n> ")
        if user_input.lower() in ["exit", "quit", "q"]:
            print("Exiting...")
            break
    except KeyboardInterrupt:
        print()
        print("Exiting...")
        break
    print()
    
    messages.append({"role": "user", "content": user_input})

    response = client.chat.completions.create(
        model="deepseek-flash",
        messages=messages,
        stream=False,
        reasoning_effort="high",
        extra_body={"thinking": {"type": "enabled"}}
    )

    messages.append(response.choices[0].message)
    print(f"AI Assistant\n> {response.choices[0].message.content}")
    print()
    print("────────────────────────────────────────────────────────────")
    print()
