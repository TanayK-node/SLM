from fastapi import FastAPI
from pydantic import BaseModel
from app.engine.model import generate_response
from app.engine.rag import retrieve, ingest_folder
from app.engine.sql_engine import ask_database # NEW IMPORT

app = FastAPI()

class QueryRequest(BaseModel):
    query: str

async def route_query(query: str) -> str:
    """The Routing Agent: Determines which engine to use."""
    routing_prompt = f"""
    You are an intelligent routing agent for an enterprise AI system.
    Analyze the user's query and output EXACTLY ONE WORD from the following list:
    
    - RAG: If the query asks about specific text documents, stories, or code files.
    - SQL: If the query asks about live metrics, performance, algorithms, or database records.
    - CHAT: If the query is just casual conversation or brainstorming.

    User Query: "{query}"
    
    Output exactly one word (RAG or SQL or CHAT):
    """
    # Ask LLaMA for the route
    route = await generate_response(routing_prompt)
    route = route.strip().upper()
    
    # Fallback in case the model hallucinates
    if "RAG" in route:
        return "RAG"
    if "SQL" in route: return "SQL"
    return "CHAT"

@app.post("/chat")
async def chat(request: QueryRequest):
    # 1. Ask the Routing Agent where to send this query
    intent = await route_query(request.query)
    print(f"🚦 Routing Agent selected: {intent}")
    
    if intent == "SQL":
        # The Database Engine (Prompt is handled inside sql_engine.py)
        answer = await ask_database(request.query)
        
    elif intent == "RAG":
        # The Document Engine
        context_chunks = retrieve(request.query)
        context = "\n\n---\n\n".join(context_chunks)
        
        # RESTORED: The strict anti-hallucination RAG prompt
        prompt = f"""
        You are an expert analytical engine evaluating documents, stories, and code.
        
        CRITICAL INSTRUCTIONS:
        1. Answer the question STRICTLY using the provided Context. 
        2. If the answer is not contained in the Context, you MUST say "I cannot answer this based on the provided documents." Do not invent answers.
        3. When you pull information from a document, mention the [Source: filename] explicitly.
        4. Do not mix up characters, variables, or logic between different sources.

        Context:
        {context}

        Question:
        {request.query}
        
        Answer:
        """
        answer = await generate_response(prompt)
        
    else:
        # The Brainstorming Engine
        # RESTORED: The Chat persona prompt
        prompt = f"""
        You are a highly intelligent, secure Enterprise AI Assistant. 
        Answer the user's question directly, thoughtfully, and professionally. 
        If they are asking for code, brainstorming, or writing tasks, provide high-quality output.
        
        Question:
        {request.query}
        
        Answer:
        """
        answer = await generate_response(prompt)

    return {
        "intent_used": intent, 
        "response": answer
    }

@app.post("/ingest")
def ingest():
    ingest_folder("data") 
    return {"status": "Ingestion complete"}