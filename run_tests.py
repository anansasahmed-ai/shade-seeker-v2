import os
import subprocess
import sys
from dotenv import load_dotenv
from google import genai

load_dotenv()

MODEL_NAME = os.environ.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
gemini_key = os.environ.get("GEMINI_API_KEY")

if not gemini_key:
    try:
        import streamlit as st
        gemini_key = st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass

if not gemini_key:
    print("⚠️ Warning: GEMINI_API_KEY not found. Autonomous healing will be disabled.")
    genai_client = None
else:
    genai_client = genai.Client(api_key=gemini_key)


def analyze_and_heal(error_output: str):
    print("\n🤖 Gemini Agent: Analyzing test failure and updating skills.md automatically...")
    
    if not genai_client:
        print("❌ Cannot heal: Gemini API key is missing.")
        return

    # Read current skills.md memory
    skills_content = ""
    if os.path.exists("skills.md"):
        with open("skills.md", "r", encoding="utf-8") as f:
            skills_content = f.read()

    prompt = f"""
You are an autonomous self-healing software agent. 
A test suite execution failed with the following traceback/error output:
```
{error_output}
```

Here is the current contents of our agent memory file (`skills.md`):
```markdown
{skills_content}
```

Your task:
1. Diagnose the root cause of this failure.
2. Formulate a concise troubleshooting rule or fix description as a markdown bullet point.
3. Return ONLY the new markdown text that should be appended to `skills.md`. Do not include conversational filler, markdown code fences around the whole thing, or explanations—just output the exact text ready to be written to the file.
"""

    response = genai_client.models.generate_content(
        model=MODEL_NAME,
        contents=prompt,
    )

    new_rule = response.text.strip()

    print("\n💡 --- Gemini Generated Rule ---")
    print(new_rule)
    print("--------------------------------")

    # Automatically append the new rule to skills.md
    with open("skills.md", "a", encoding="utf-8") as f:
        f.write(f"\n\n{new_rule}")
    
    print("📝 Successfully updated `skills.md` automatically!")


def run_test_suite():
    print("🤖 Test Runner: Starting test execution...")
    
    result = subprocess.run(
        [sys.executable, "-m", "pytest"],
        capture_output=True,
        text=True
    )
    
    print("\n--- STDOUT ---")
    print(result.stdout)
    
    if result.stderr:
        print("\n--- STDERR ---")
        print(result.stderr)
        
    print(f"\nExit Code: {result.returncode}")
    
    if result.returncode == 0:
        print("✅ All tests passed successfully! No healing needed.")
    else:
        print("❌ Tests failed! Engaging autonomous learning loop...")
        full_error = result.stdout + "\n" + result.stderr
        analyze_and_heal(full_error)
        
    return result.returncode


if __name__ == "__main__":
    run_test_suite()
