import httpx
import asyncio
import os
import json
import re
from dotenv import load_dotenv

# Load .env so PAGEINDEX_API_KEY is available when running via uvicorn
load_dotenv()

# ── PageIndex API config ──────────────────────────────────────────────────────
PAGEINDEX_BASE_URL = "https://api.pageindex.ai"

def _api_key() -> str:
    """Read key at call time so .env changes are picked up without restart."""
    return os.getenv("PAGEINDEX_API_KEY", "")

PAGEINDEX_TIMEOUT = httpx.Timeout(connect=10.0, read=120.0, write=30.0, pool=10.0)

# ── In-memory registry: filename → {doc_id, tree, node_map, mode} ────────────
# This persists as long as the FastAPI server is running.
# Key = original filename e.g. "research_paper.pdf"
REGISTRY: dict = {}

def get_mode(score: float = 0) -> str:
    """Mode is now set directly, not scored."""
    return "pageindex"


# ── PageIndex API helpers ─────────────────────────────────────────────────────
async def _submit_pdf(pdf_path: str) -> str:
    """Upload PDF to PageIndex and return doc_id."""
    async with httpx.AsyncClient(timeout=PAGEINDEX_TIMEOUT) as client:
        with open(pdf_path, "rb") as f:
            resp = await client.post(
                f"{PAGEINDEX_BASE_URL}/doc/",
                headers={"api_key": _api_key()},
                files={"file": (os.path.basename(pdf_path), f, "application/pdf")},
                data={"if_retrieval": "true"}
            )
        resp.raise_for_status()
        return resp.json()["doc_id"]


async def _wait_for_tree(doc_id: str, retries: int = 30, delay: int = 10) -> list:
    """Poll GET /doc/{doc_id}/?type=tree until status is 'completed', return tree list."""
    async with httpx.AsyncClient(timeout=PAGEINDEX_TIMEOUT) as client:
        for attempt in range(retries):
            resp = await client.get(
                f"{PAGEINDEX_BASE_URL}/doc/{doc_id}/",
                headers={"api_key": _api_key()},
                params={"type": "tree"}
            )
            print(f"   [poll #{attempt+1}] HTTP {resp.status_code} — raw response:")
            print(f"   {resp.text[:2000]}")  # print up to 2000 chars
            if resp.status_code == 200:
                data = resp.json()
                status = data.get("status", "")
                if status == "completed":
                    tree = data.get("result", [])  # API uses 'result', not 'tree'
                    print(f"\n🌳 FULL TREE JSON for doc_id={doc_id}:")
                    print(json.dumps(tree, indent=2))
                    return tree
                if status == "failed":
                    raise RuntimeError(f"PageIndex tree build failed for doc_id={doc_id}")
                print(f"   ⏳ PageIndex still processing (status={status})... retrying in {delay}s")
            await asyncio.sleep(delay)
    raise TimeoutError(f"PageIndex tree not ready after {retries * delay}s")


def _build_node_map(tree: list) -> dict:
    """Flatten the tree into node_id → node dict for O(1) lookup."""
    node_map = {}
    def _recurse(nodes):
        for node in nodes:
            node_map[node["node_id"]] = node
            if node.get("nodes"):
                _recurse(node["nodes"])
    _recurse(tree)
    return node_map


# ── Public API ────────────────────────────────────────────────────────────────
async def build_pageindex(pdf_path: str, filename: str):
    """
    Background task: submit PDF to PageIndex, wait for tree, store in REGISTRY.
    Called from main.py via asyncio.create_task().
    """
    try:
        print(f"🌲 Building PageIndex tree for: {filename}")
        doc_id   = await _submit_pdf(pdf_path)
        print(f"   📤 Submitted. doc_id={doc_id} — polling for tree...")
        tree     = await _wait_for_tree(doc_id)
        node_map = _build_node_map(tree)

        REGISTRY[filename] = {
            "doc_id":   doc_id,
            "tree":     tree,
            "node_map": node_map,
            "mode":     "pageindex",   # always pageindex if user opted in
        }
        print(f"✅ PageIndex ready for '{filename}' | nodes={len(node_map)}")
    except Exception as e:
        print(f"❌ PageIndex build failed for '{filename}': {e}")
        # Don't crash — FAISS will be used as fallback


async def pageindex_retrieve(query: str, filename: str, model_fn) -> str:
    """
    Given a query and filename, use the PageIndex tree to retrieve
    the most relevant node content. Returns a string of context.

    model_fn = generate_response from model.py (injected to avoid circular import)
    """
    entry = REGISTRY.get(filename)
    if not entry:
        return ""

    tree     = entry["tree"]
    node_map = entry["node_map"]

    # Build the tree summary for the LLM to navigate
    def _summarize_tree(nodes_list, depth=0) -> str:
        lines = []
        for n in nodes_list:
            indent = "  " * depth
            lines.append(f'{indent}{{"node_id": "{n["node_id"]}", "title": "{n.get("title","")}", "summary": "{n.get("summary","")}"}}')
            if n.get("nodes"):
                lines.extend(_summarize_tree(n["nodes"], depth + 1).split("\n"))
        return "\n".join(lines)

    tree_summary = _summarize_tree(tree)

    search_prompt = f"""You are a document navigation expert.
You are given a question and a tree structure of a document.
Each node contains a node id, node title, and a corresponding summary.
Your task is to find all nodes that are likely to contain the answer to the question.

Question: {query}

Document Tree:
{tree_summary}

Please reply ONLY in the following JSON format:
{{
    "thinking": "<Your thinking process on which nodes are relevant to the question>",
    "node_list": ["node_id_1", "node_id_2"]
}}"""

    raw = await model_fn(search_prompt)

    # Parse node list from LLM response
    try:
        raw_clean = raw.strip()
        # Strip markdown code blocks if present
        raw_clean = re.sub(r"```json|```", "", raw_clean).strip()
        # Extract JSON object
        match = re.search(r'\{.*\}', raw_clean, re.DOTALL)
        if match:
            data = json.loads(match.group())
            node_ids = data.get("node_list", [])
            print(f"🧠 PageIndex LLM Thinking:\n{data.get('thinking', '')}")
        else:
            node_ids = []
    except Exception as e:
        print(f"⚠️ PageIndex JSON parse error: {e}\nRaw output: {raw}")
        node_ids = []

    print(f"🎯 PageIndex Selected Nodes: {node_ids}")
    
    if not node_ids:
        return ""

    # Extract content from the in-memory node_map (content is embedded in tree nodes)
    context_parts = []
    for nid in node_ids[:5]:  # cap at 5 nodes
        node = node_map.get(nid)
        if node:
            title   = node.get("title", nid)
            # API returns content under 'text' key
            content = node.get("text", node.get("content", node.get("summary", "")))
            if content:
                context_parts.append(f"[{title}]\n{content}")

    if not context_parts:
        print("⚠️ PageIndex: Selected nodes were not found in node_map or had no content.")
        
    return "\n\n---\n\n".join(context_parts)