import httpx
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3.1:8b" # Change to a quantized model if possible (e.g., llama3.1:8b-q4_K_M)

async def generate_response(prompt: str):
    # Using an async client prevents the 150s wait from blocking your entire API
    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await client.post(
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": False,
                "options": {
                    "num_ctx": 8192 
                }
            }
        )
        data = response.json()
        print("OLLAMA RAW RESPONSE:", data)

        return data.get("response", "No response key found")

async def stream_response(prompt: str):
    """Async generator to stream Ollama responses token-by-token."""
    async with httpx.AsyncClient(timeout=300.0) as client:
        async with client.stream(
            "POST",
            OLLAMA_URL,
            json={
                "model": MODEL_NAME,
                "prompt": prompt,
                "stream": True,
                "options": {
                    "num_ctx": 8192
                }
            }
        ) as response:
            async for line in response.aiter_lines():
                if not line:
                    continue

                try:
                    data = json.loads(line)
                    if "response" in data:
                        yield data["response"]
                    if data.get("done"):
                        break
                except json.JSONDecodeError:
                    continue