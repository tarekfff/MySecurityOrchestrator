import os
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

model = "gemini-embedding-001"
text = "test"

result = client.models.embed_content(
    model=model,
    contents=text,
    config=types.EmbedContentConfig(
        task_type="RETRIEVAL_DOCUMENT",
        output_dimensionality=768
    ),
)

print(f"Model: {model}")
print(f"Embedding length: {len(result.embeddings[0].values)}")
