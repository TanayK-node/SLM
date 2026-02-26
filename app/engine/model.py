import httpx

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
                "stream": False
            }
        )
        data = response.json()
        print("OLLAMA RAW RESPONSE:", data)

        return data.get("response", "No response key found")