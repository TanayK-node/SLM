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
    # Split by double newline to preserve function/class boundaries in scripts
    paragraphs = text.split("\n\n")
    
    current_chunk = ""
    for para in paragraphs:
        if len(current_chunk) + len(para) < chunk_size:
            current_chunk += para + "\n\n"
        else:
            if current_chunk:
                chunks.append(current_chunk.strip())
            # Handle the overlap
            overlap_text = current_chunk[-overlap:] if len(current_chunk) > overlap else current_chunk
            current_chunk = overlap_text + para + "\n\n"
            
    if current_chunk:
        chunks.append(current_chunk.strip())
        
    return chunks

def load_full_file(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        return f.read()

def ingest_folder(folder_path):
    global index, documents
    
    documents = []
    
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        
        if filename.endswith(".txt") or filename.endswith(".py"):
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read() # Only read ONCE
                
                # Use the improved semantic chunker
                raw_chunks = chunk_text(text)
                
                # Inject metadata directly into the text the model will read
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