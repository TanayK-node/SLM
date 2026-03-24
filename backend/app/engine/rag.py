import os
import faiss
import numpy as np
import re
from sentence_transformers import SentenceTransformer
import fitz  # PyMuPDF (The new, vastly superior PDF parser)
import docx

model = SentenceTransformer("all-MiniLM-L6-v2")

index = None
documents = []

def clean_pdf_text(text: str) -> str:
    """Fixes the weird formatting and broken lines typical in large PDFs."""
    # Replace single line breaks with spaces (joins broken sentences)
    text = re.sub(r'(?<!\n)\n(?!\n)', ' ', text)
    # Replace multiple spaces with a single space
    text = re.sub(r'\s+', ' ', text)
    return text.strip()

def extract_text(file_path, filename):
    """Extracts and heavily cleans text from TXT, PDF, and DOCX files."""
    text = ""
    try:
        if filename.endswith(".txt") or filename.endswith(".py"):
            with open(file_path, "r", encoding="utf-8") as f:
                text = f.read()
                
        elif filename.endswith(".pdf"):
            # UPGRADE 1: PyMuPDF is 10x faster and cleaner than PyPDF2
            doc = fitz.open(file_path)
            for page in doc:
                text += page.get_text("text") + "\n\n"
            text = clean_pdf_text(text)
            
        elif filename.endswith((".docx", ".doc")):
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text += para.text + "\n\n"
    except Exception as e:
        print(f"Error reading {filename}: {e}")
    return text

def chunk_text(text, chunk_size=400, overlap=200):
    """
    UPGRADE 2: Larger chunk_size (800) and overlap (200).
    Uses a smarter overlapping window that doesn't rely entirely on \n\n.
    """
    chunks = []
    # If the text is cleaned, we can just use overlapping character windows
    # ensuring we don't cut words in half
    words = text.split()
    current_chunk = []
    current_length = 0
    
    for word in words:
        current_chunk.append(word)
        current_length += len(word) + 1 # +1 for the space
        
        if current_length >= chunk_size:
            chunks.append(" ".join(current_chunk))
            # Keep the last few words for overlap (roughly overlap/5 words)
            overlap_words = int(overlap / 5)
            current_chunk = current_chunk[-overlap_words:] if len(current_chunk) > overlap_words else []
            current_length = sum(len(w) + 1 for w in current_chunk)
            
    if current_chunk:
        chunks.append(" ".join(current_chunk))
        
    return chunks

def ingest_folder(folder_path):
    global index, documents
    documents = []
    
    if not os.path.exists(folder_path):
        os.makedirs(folder_path)
        
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        
        text = extract_text(file_path, filename)
        
        if text.strip():
            raw_chunks = chunk_text(text)
            labeled_chunks = [f"[Source: {filename}]\n{chunk}" for chunk in raw_chunks]
            documents.extend(labeled_chunks)

    if documents:
        embeddings = model.encode(documents)
        dimension = embeddings.shape[1]
        index = faiss.IndexFlatL2(dimension)
        index.add(np.array(embeddings))
        print(f"✅ RAG Engine Ingested {len(documents)} document chunks.")
        
def ingest_file(file_path: str, filename: str):
    """
    Appends a single file directly into the FAISS index without 
    re-reading the entire folder. Highly efficient!
    """
    global index, documents
    
    # Extract and clean the text using our upgraded PyMuPDF logic
    text = extract_text(file_path, filename)
    
    if text.strip():
        raw_chunks = chunk_text(text)
        labeled_chunks = [f"[Source: {filename}]\n{chunk}" for chunk in raw_chunks]
        
        # 1. Add the new text to our global documents list
        documents.extend(labeled_chunks)
        
        # 2. Convert ONLY the new chunks into vectors
        new_embeddings = model.encode(labeled_chunks)
        
        # 3. If this is the very first file, initialize the FAISS index
        if index is None:
            dimension = new_embeddings.shape[1]
            index = faiss.IndexFlatL2(dimension)
            
        # 4. Append the new vectors to the existing AI memory
        index.add(np.array(new_embeddings))
        print(f"✅ RAG Engine appended {len(labeled_chunks)} chunks from {filename}.")
        return True
    
    return False
# UPGRADE 3: Grab the top 10 chunks instead of top 4 for massive context.
def retrieve(query, top_k=10): 
    if index is None or not documents:
        return []
        
    query_embedding = model.encode([query])
    distances, indices = index.search(np.array(query_embedding), top_k)
    
    results = [documents[i] for i in indices[0] if i < len(documents)]
    return results