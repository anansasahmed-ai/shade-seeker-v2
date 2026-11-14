import time

from dotenv import load_dotenv

load_dotenv()

from agent import MODEL_NAME, chat

print(f"🌞 Shade Seeker Agent Initialized ({MODEL_NAME})!")
print("Type 'exit' or 'quit' to end the session.")
print(
    "Example: 'Which side of the car should I sit on from San Francisco to San"
    " Jose leaving tomorrow at 2:00 PM?'"
)
print("-" * 60)

while True:
  try:
    user_input = input("\nYou: ")
    if user_input.lower() in ["exit", "quit"]:
      print("Goodbye!")
      break

    if not user_input.strip():
      continue

    print("\nThinking and computing route shade...")

    max_retries = 3
    retry_delay = 3
    response = None

    for attempt in range(max_retries):
      try:
        response = chat.send_message(user_input)
        break
      except Exception as e:
        if "503" in str(e) and attempt < max_retries - 1:
          print(
              f"\n[Server busy, retrying in {retry_delay}s... (Attempt"
              f" {attempt + 1}/{max_retries})]"
          )
          time.sleep(retry_delay)
          retry_delay *= 2
        else:
          raise e

    if response:
      print(f"\nAgent:\n{response.text}")

  except KeyboardInterrupt:
    print("\nGoodbye!")
    break
  except Exception as e:
    print(f"\nError: {e}")
