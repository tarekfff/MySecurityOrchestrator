import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

print("Listing available models...")
for model in client.models.list():
    if "embed" in model.name:
        print(f"Model: {model.name}")
