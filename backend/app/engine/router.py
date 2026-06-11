from app.engine.pageindex import get_mode, REGISTRY
import os

def get_document_mode(filename: str) -> str:
    """
    Returns the retrieval mode for a given filename.
    Checks REGISTRY first (set during upload).
    Falls back to 'rag' if not found (e.g. txt/docx files).
    """
    entry = REGISTRY.get(filename)
    if entry:
        return entry["mode"]
    return "rag"