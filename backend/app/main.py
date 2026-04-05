import os
import shutil
from pydantic import BaseModel
from app.engine.model import generate_response, stream_response # UPDATED
from app.engine.rag import retrieve, ingest_folder, ingest_file
from app.engine.sql_engine import ask_database, connect_to_database # NEW IMPORT
from fastapi import FastAPI, HTTPException, UploadFile, File # NEW IMPORTS
from fastapi.responses import StreamingResponse # NEW IMPORT
from app.engine.tabular_engine import ask_spreadsheet, process_file_to_db # NEW IMPORT
from fastapi.middleware.cors import CORSMiddleware # NEW IMPORT
from typing import List, Optional

app = FastAPI()

# NEW: Add CORS middleware to allow your Next.js frontend to talk to FastAPI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # In production, change this to your actual frontend URL
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Intent-Used"], # CRITICAL: Allow the browser to read this header
)

class ChatMessage(BaseModel):
    role: str
    content: str

class QueryRequest(BaseModel):
    query: str
    history: Optional[List[ChatMessage]] = []

class DBConnectRequest(BaseModel):
    connection_string: str

def format_history(history: List[ChatMessage]) -> str:
    """Converts the JSON history array into readable text for the LLM."""
    if not history:
        return "No previous context."
    return "\n".join([f"{msg.role.upper()}: {msg.content}" for msg in history])

async def route_query(query: str, history_text: str) -> str:
    """The Routing Agent: Determines which engine to use."""
    routing_prompt = f"""
    You are an intelligent routing agent for an enterprise AI system.
    Analyze the user's query and output EXACTLY ONE WORD (RAG, SQL, CSV, or CHAT).
    
    - RAG: ONLY if the query explicitly asks to search, summarize, or read an uploaded document, PDF, or knowledge base.
    - SQL: ONLY if the query asks about live connected database metrics (users, trades, etc.).
    - CSV: ONLY if the query asks to calculate or analyze an uploaded spreadsheet.
    - CHAT: Default fallback. Use this for casual conversation, drafting emails, writing code, brainstorming, or general knowledge questions.
    === PREVIOUS CONVERSATION CONTEXT ===
    {history_text}
    User Query: "{query}"
    
    Output exactly one word (RAG or SQL or CHAT or CSV):
    """
    # Ask LLaMA for the route
    route = await generate_response(routing_prompt)
    route = route.strip().upper()
    
    # Fallback in case the model hallucinates
    if "RAG" in route:
        return "RAG"
    if "SQL" in route: return "SQL"
    if "CSV" in route: return "CSV"
    return "CHAT"

@app.post("/upload_file")
async def upload_file(file: UploadFile = File(...)):
    """Endpoint for users to upload CSV or Excel files for analysis."""
    # 1. Save the uploaded file temporarily to the disk
    os.makedirs("data/uploads", exist_ok=True)
    file_location = f"data/uploads/{file.filename}"
    
    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)
        
    # 2. Process the file and convert it to a database
    success, message = process_file_to_db(file_location, file.filename)
    
    if success:
        return {"status": "success", "message": message}
    else:
        raise HTTPException(status_code=400, detail=message)
    
@app.post("/upload_document")
async def upload_document(file: UploadFile = File(...)):
    """Endpoint for users to upload PDF, DOCX, or TXT files for RAG."""
    allowed_extensions = {".pdf", ".docx", ".txt"}
    ext = os.path.splitext(file.filename)[1].lower()

    if ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Please upload a .pdf, .docx, or .txt file."
        )

    os.makedirs("data/uploads", exist_ok=True)
    file_location = f"data/uploads/{file.filename}"

    with open(file_location, "wb+") as file_object:
        shutil.copyfileobj(file.file, file_object)

    ingest_file(file_location, file.filename)
    return {"status": "success", "message": f"Document '{file.filename}' ingested into RAG successfully."}

@app.post("/connect_db")
def connect_db(request: DBConnectRequest):
    """Endpoint for companies to plug in their database via URL."""
    success, message = connect_to_database(request.connection_string)
    
    if success:
        return {"status": "success", "message": message}
    else:
        # If the connection fails (bad password, wrong URL), return a 400 Bad Request
        raise HTTPException(status_code=400, detail=message)

@app.post("/chat")
async def chat(request: QueryRequest):
    history_text = format_history(request.history)
    intent = await route_query(request.query, history_text)
    print(f"🚦 Routing Agent selected: {intent}")

    async def response_generator():
        if intent == "SQL":
            async for chunk in ask_database(request.query, history_text):
                yield chunk
        
        elif intent == "RAG":
            context_chunks = retrieve(request.query)
            context = "\n\n---\n\n".join(context_chunks)
            prompt = f"""
            You are an expert analytical engine evaluating documents, stories, and code.
            
            CRITICAL INSTRUCTIONS:
            1. Answer the question STRICTLY using the provided Context. 
            2. If the answer is not contained in the Context, you MUST say "I cannot answer this based on the provided documents." Do not invent answers.
            3. When you pull information from a document, mention the [Source: filename] explicitly.
            4. Do not mix up characters, variables, or logic between different sources.

            Context:
            {context}
            === PREVIOUS CONVERSATION ===
            {history_text}
            Question:
            {request.query}
            
            Answer:
            """
            async for chunk in stream_response(prompt):
                yield chunk

        elif intent == "CSV":
            # For now, CSV still uses non-streaming fallback or you can update tabular_engine too
            answer = await ask_spreadsheet(request.query, history_text)
            yield answer
            
        else:
            prompt = f"""
            You are a highly intelligent, secure Enterprise AI Assistant. 
            Answer the user's question directly, thoughtfully, and professionally. 
            If they are asking for code, brainstorming, or writing tasks, provide high-quality output.
            
            === PREVIOUS CONVERSATION ===
            {history_text}
            Question:
            {request.query}
            
            Answer:
            """
            async for chunk in stream_response(prompt):
                yield chunk

    return StreamingResponse(
        response_generator(),
        media_type="text/plain",
        headers={
            "X-Intent-Used": intent,
            "Access-Control-Expose-Headers": "X-Intent-Used"
        }
    )

@app.post("/ingest")
def ingest():
    ingest_folder("data") 
    return {"status": "Ingestion complete"}

