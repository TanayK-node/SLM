import httpx
import json

OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "qwen2.5"

# ✅ Explicit timeout: connect=10s, read=300s, write=30s, pool=10s
OLLAMA_TIMEOUT = httpx.Timeout(
    connect=10.0,   # time to establish connection
    read=600.0,     # time to wait for response data  ← THIS was the culprit (was 5s default)
    write=30.0,     # time to send the request
    pool=10.0       # time to acquire connection from pool
)

async def generate_response(prompt: str):
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
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
    async with httpx.AsyncClient(timeout=OLLAMA_TIMEOUT) as client:
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