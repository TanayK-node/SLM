import os
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

model = SentenceTransformer("all-MiniLM-L6-v2")

index = None
documents = []

def chunk_text(text, chunk_size=500, overlap=100):
    """
    Semantic chunking: Tries to keep paragraphs/functions together 
    by splitting on double newlines, with a fallback to single newlines.
    """
    chunks = []
    paragraphs = text.split("\n\n")
    
    current_chunk = ""
    for para in paragraphs:
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + para + "\n\n"
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks

def extract_text(file_path: str, filename: str) -> str:
    """Extract raw text from .txt, .py, .pdf, or .docx files."""
    ext = os.path.splitext(filename)[1].lower()
    
    if ext in (".txt", ".py"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    
    elif ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(file_path)
        pages = [page.extract_text() for page in reader.pages if page.extract_text()]
        return "\n\n".join(pages)
    
    elif ext == ".docx":
        from docx import Document
        doc = Document(file_path)
        paragraphs = [p.text for p in doc.paragraphs if p.text.strip()]
        return "\n\n".join(paragraphs)
    
    return ""

def ingest_file(file_path: str, filename: str):
    """Ingest a single document and add it incrementally to the RAG index."""
    global index, documents
    
    text = extract_text(file_path, filename)
    if not text.strip():
        return
    
    raw_chunks = chunk_text(text)
    labeled_chunks = [f"[Source: {filename}]\n{chunk}" for chunk in raw_chunks]
    documents.extend(labeled_chunks)
    
    embeddings = model.encode(labeled_chunks)
    embeddings_np = np.array(embeddings)
    
    if index is None:
        dimension = embeddings_np.shape[1]
        index = faiss.IndexFlatL2(dimension)
    
    index.add(embeddings_np)

def ingest_folder(folder_path):
    """Ingest all supported files in a folder (used for initial seeding)."""
    global index, documents
    
    documents = []
    supported_exts = (".txt", ".py", ".pdf", ".docx")
    
    for filename in os.listdir(folder_path):
        if not any(filename.endswith(ext) for ext in supported_exts):
            continue
        file_path = os.path.join(folder_path, filename)
        text = extract_text(file_path, filename)
        if not text.strip():
            continue
        raw_chunks = chunk_text(text)
        labeled_chunks = [f"[Source: {filename}]\n{chunk}" for chunk in raw_chunks]
        documents.extend(labeled_chunks)

    if documents:
        embeddings = model.encode(documents)
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(np.array(embeddings))

def retrieve(query, top_k=4): # Increased top_k slightly for better context coverage
    if index is None or not documents:
        return []
        
    query_embedding = model.encode([query])
    distances, indices = index.search(np.array(query_embedding), top_k)
    
    results = [documents[i] for i in indices[0] if i < len(documents)]
    return results