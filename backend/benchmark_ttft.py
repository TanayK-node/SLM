"""
benchmark_ttft.py — Automated TTFT benchmark for SLM project (Test 4 in the paper plan).

Measures Time to First Token (TTFT) and end-to-end latency across:
  - Transports : HTTP streaming (/chat)  vs  WebSocket (/ws/chat)
  - Query modes: CHAT, RAG, SQL
  - Complexity  : "simple" vs "complex" queries within each mode

Usage (run from backend/ with uvicorn already running):
    python benchmark_ttft.py
    python benchmark_ttft.py --n 10 --host localhost --port 8000
    python benchmark_ttft.py --n 5  --modes CHAT SQL
    python benchmark_ttft.py --warmup 2 --delay 2.0

Output (in results/ directory):
    ttft_raw_<timestamp>.json      -- every individual measurement (never deleted)
    ttft_summary_<timestamp>.csv   -- mean ± std table, paste directly into paper
    ttft_summary_<timestamp>.txt   -- same as stdout, saved for reference

Design notes:
  - First-run: run_index == 1 is defined as the "first-run" observation for each
    query. It is always reported separately and never pooled with warm runs.
    This is the first repetition of that query, not a session-level cold start.
    Warmup queries (--warmup N, not recorded) load the model before run 1 fires.
    Set --warmup 0 to include the true model-load overhead in the first run.
  - Interleaving: for each (query, run_index) pair, HTTP and WS are fired
    back-to-back before advancing. On odd run_index, HTTP goes first; on even,
    WS goes first. This eliminates ordering bias while controlling for load drift.
  - Output size: response_chars is recorded for every run so TTFT comparisons
    can be shown to be independent of generation length.
  - Intent consistency: expected_intent vs actual_intent is compared automatically.
  - Retrieval latency: only available via WS status events. HTTP retrieval_ms is
    always None; the report notes this explicitly.
  - Statistics: mean, std, and median per cell. Median is reported because LLM
    latency distributions can be right-skewed.
  - Significance: a paired t-test (scipy.stats.ttest_rel) is used because HTTP
    and WS measurements are paired by (query, run_index). p < 0.05 is the
    threshold used in the report.
  - Inter-run sleep: --delay (default 2s) between consecutive measurements
    reduces KV-cache and OS-buffer warm bias.

Requirements:
    pip install httpx websockets scipy
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import statistics
import sys
import time
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import httpx

try:
    import websockets
    import websockets.exceptions
    from websockets.asyncio.client import connect as ws_connect
except ImportError:
    websockets = None

try:
    from scipy import stats as scipy_stats

    SCIPY_AVAILABLE = True
except ImportError:
    SCIPY_AVAILABLE = False

# Benchmark queries grouped by intent and complexity.
# Each tuple contains:
# (query_id, query_text, complexity, expected_intent)
CHAT_QUERIES: list[tuple[str, str, str, str]] = [
    ("chat_s1", "What is a REST API?", "simple", "CHAT"),
    ("chat_s2", "Define machine learning in one sentence.", "simple", "CHAT"),
    ("chat_s3", "What does ACID stand for in databases?", "simple", "CHAT"),
    (
        "chat_s4",
        "What is the difference between authentication and authorisation?",
        "simple",
        "CHAT",
    ),
    ("chat_s5", "What is data sovereignty?", "simple", "CHAT"),
    (
        "chat_c1",
        "What are the key challenges of deploying AI in enterprise environments?",
        "complex",
        "CHAT",
    ),
    (
        "chat_c2",
        "Explain the difference between RAG and fine-tuning an LLM, including trade-offs.",
        "complex",
        "CHAT",
    ),
    (
        "chat_c3",
        "Compare monolithic and microservice architectures for a high-throughput trading platform.",
        "complex",
        "CHAT",
    ),
    (
        "chat_c4",
        "What are the security implications of prompt injection in LLM-based enterprise applications?",
        "complex",
        "CHAT",
    ),
    (
        "chat_c5",
        "Describe how vector databases work and when you would prefer them over traditional SQL indexes.",
        "complex",
        "CHAT",
    ),
]

RAG_QUERIES: list[tuple[str, str, str, str]] = [
    ("rag_s1", "What is the main topic of the uploaded document?", "simple", "RAG"),
    ("rag_s2", "What system is described in the document?", "simple", "RAG"),
    ("rag_s3", "Who are the intended users of the system described?", "simple", "RAG"),
    ("rag_s4", "What technology stack is mentioned in the document?", "simple", "RAG"),
    ("rag_s5", "What problem does the document aim to solve?", "simple", "RAG"),
    (
        "rag_c1",
        "Summarize the key findings from the document in detail.",
        "complex",
        "RAG",
    ),
    (
        "rag_c2",
        "What recommendations are made in the document and why?",
        "complex",
        "RAG",
    ),
    (
        "rag_c3",
        "How does the proposed system compare to existing approaches mentioned in the document?",
        "complex",
        "RAG",
    ),
    (
        "rag_c4",
        "What are the limitations acknowledged by the authors in the document?",
        "complex",
        "RAG",
    ),
    (
        "rag_c5",
        "Provide a detailed technical summary of the methodology described in the document.",
        "complex",
        "RAG",
    ),
]

SQL_QUERIES: list[tuple[str, str, str, str]] = [
    ("sql_s1", "How many trades are recorded in total?", "simple", "SQL"),
    ("sql_s2", "How many users are in the system?", "simple", "SQL"),
    ("sql_s3", "List all algorithm names.", "simple", "SQL"),
    ("sql_s4", "How many active algorithms are there?", "simple", "SQL"),
    ("sql_s5", "What is the total profit across all trades?", "simple", "SQL"),
    (
        "sql_c1",
        "Which algorithm generated the highest total profit? Show the name and total.",
        "complex",
        "SQL",
    ),
    ("sql_c2", "List all users and the algorithms they created.", "complex", "SQL"),
    (
        "sql_c3",
        "What is the average profit per trade grouped by algorithm?",
        "complex",
        "SQL",
    ),
    (
        "sql_c4",
        "Which symbol had the highest single-trade profit and which algorithm executed it?",
        "complex",
        "SQL",
    ),
    (
        "sql_c5",
        "Show the total profit and loss per user by joining users, algorithms, and trades.",
        "complex",
        "SQL",
    ),
]

# Central lookup used to iterate benchmark modes dynamically.
ALL_QUERIES: dict[str, list[tuple[str, str, str, str]]] = {
    "CHAT": CHAT_QUERIES,
    "RAG": RAG_QUERIES,
    "SQL": SQL_QUERIES,
}

# Lightweight query used to warm model weights and caches before measurement.
WARMUP_QUERY = "What is machine learning?"

SEP = "-" * 110
SEP2 = "=" * 110


@dataclass
class Measurement:
    """Captures the result of a single benchmark run."""
    run_id: str
    query_label: str
    query_text: str
    complexity: str  # "simple" | "complex"
    expected_intent: str  # "CHAT" | "RAG" | "SQL"
    actual_intent: Optional[str]  # what the router actually returned
    transport: str  # "http" | "ws"
    run_index: int  # 1 = first run of this query, 2..N = subsequent
    is_first_run: bool  # True iff run_index == 1 for this query
    ttft_ms: Optional[float]
    end_to_end_ms: Optional[float]
    retrieval_ms: Optional[float]  # RAG/WS only; always None for HTTP
    intent_ms: Optional[float]  # WS only; always None for HTTP
    response_chars: int = 0  # total characters in the streamed response
    intent_correct: bool = False  # expected_intent == actual_intent
    error: Optional[str] = None


@dataclass
class _TimingFields:
    """Groups timing values collected during a single measurement.

    Keeping these fields together avoids passing a large number of
    timing-related parameters into _build_measurement().
    """

    ttft_ms: Optional[float]
    end_to_end_ms: Optional[float]
    retrieval_ms: Optional[float]
    intent_ms: Optional[float]
    response_chars: int
    error: Optional[str]


@asynccontextmanager
async def _http_client(total: float = 180.0) -> AsyncIterator[httpx.AsyncClient]:
    """Shared HTTP client configuration used by all benchmark requests."""
    limits = httpx.Limits(max_connections=5, max_keepalive_connections=2)
    timeout = httpx.Timeout(connect=10.0, read=total, write=30.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout, limits=limits) as client:
        yield client


# Keep request payload construction consistent across transports.
def _make_payload(query_text: str, role: str) -> dict:
    return {"query": query_text, "history": [], "role": role}


def _build_measurement(
    run_id: str,
    query_label: str,
    query_text: str,
    complexity: str,
    expected_intent: str,
    actual_intent: Optional[str],
    transport: str,
    run_index: int,
    timing: _TimingFields,
) -> Measurement:
    """Centralises Measurement creation so HTTP and WS populate fields identically."""

    intent_correct = (
        actual_intent is not None
        and actual_intent.strip().upper() == expected_intent.strip().upper()
    )
    return Measurement(
        run_id=run_id,
        query_label=query_label,
        query_text=query_text,
        complexity=complexity,
        expected_intent=expected_intent,
        actual_intent=actual_intent,
        transport=transport,
        run_index=run_index,
        is_first_run=(run_index == 1),
        ttft_ms=timing.ttft_ms,
        end_to_end_ms=timing.end_to_end_ms,
        retrieval_ms=timing.retrieval_ms,
        intent_ms=timing.intent_ms,
        response_chars=timing.response_chars,
        intent_correct=intent_correct,
        error=timing.error,
    )


async def _drain_http_stream(
    resp: httpx.Response, t_send: float
) -> tuple[Optional[float], int]:
    """TTFT is defined as arrival of the first non-empty streamed chunk."""
    ttft_ms = None
    first_chunk = True
    response_chars = 0
    async for chunk in resp.aiter_text():
        if chunk:
            response_chars += len(chunk)
            if first_chunk:
                ttft_ms = (time.perf_counter() - t_send) * 1000
                first_chunk = False
    return ttft_ms, response_chars


def _classify_ws_message(
    msg: dict,
    t_send: float,
    ttft_ms: Optional[float],
    intent_ms: Optional[float],
    retrieval_ms: Optional[float],
    actual_intent: Optional[str],
    response_chars: int,
) -> tuple[Optional[float], Optional[float], Optional[float], Optional[str], int, bool]:
    """Process one WS message and return updated timing state.
    Returns (ttft_ms, intent_ms, retrieval_ms, actual_intent, response_chars, done)."""
    now = time.perf_counter()
    done = False
    msg_type = msg.get("type", "")

    # WS exposes intermediate pipeline events that HTTP cannot observe.
    if msg_type == "intent":
        intent_ms = (now - t_send) * 1000
        actual_intent = msg.get("intent")
    # Retrieval completes when generation begins.
    elif msg_type == "status" and msg.get("message") == "Generating response":
        retrieval_ms = (now - t_send) * 1000
    elif msg_type == "token":
        content = msg.get("content", "")
        response_chars += len(content)
        if ttft_ms is None:
            ttft_ms = (now - t_send) * 1000
    elif msg_type == "done":
        done = True

    return ttft_ms, intent_ms, retrieval_ms, actual_intent, response_chars, done


async def measure_http(
    query_label: str,
    query_text: str,
    complexity: str,
    expected_intent: str,
    run_index: int,
    base_url: str,
    role: str = "Standard_User",
) -> Measurement:
    """POST /chat with streaming. intent_ms and retrieval_ms are not available
    via HTTP and are recorded as None."""
    run_id = f"{query_label}_http_r{run_index:02d}"
    payload = _make_payload(query_text, role)
    actual_intent = None
    t_send = time.perf_counter()

    timing = _TimingFields(
        ttft_ms=None,
        end_to_end_ms=None,
        retrieval_ms=None,
        intent_ms=None,
        response_chars=0,
        error=None,
    )

    try:
        async with _http_client() as client:
            t_send = time.perf_counter()
            async with client.stream(
                "POST",
                f"{base_url}/chat",
                json=payload,
                headers={"Content-Type": "application/json"},
            ) as resp:
                resp.raise_for_status()
                actual_intent = resp.headers.get("x-intent-used")
                ttft_ms, resp_chars = await _drain_http_stream(resp, t_send)
                timing.ttft_ms = ttft_ms
                timing.response_chars = resp_chars
        timing.end_to_end_ms = (time.perf_counter() - t_send) * 1000
    except Exception as exc:
        timing.end_to_end_ms = (time.perf_counter() - t_send) * 1000
        timing.error = str(exc)

    return _build_measurement(
        run_id,
        query_label,
        query_text,
        complexity,
        expected_intent,
        actual_intent,
        "http",
        run_index,
        timing,
    )


async def measure_ws(
    query_label: str,
    query_text: str,
    complexity: str,
    expected_intent: str,
    run_index: int,
    base_url: str,
    role: str = "Standard_User",
    per_message_timeout: float = 180.0,
) -> Measurement:
    """Opens a WebSocket to /ws/chat and measures intent_ms, retrieval_ms
    (RAG only), ttft_ms, end_to_end_ms, and response_chars."""
    if websockets is None:
        raise RuntimeError(
            "websockets package not installed. Run: pip install websockets"
        )

    run_id = f"{query_label}_ws_r{run_index:02d}"
    ws_url = (
        base_url.replace("http://", "ws://").replace("https://", "wss://") + "/ws/chat"
    )
    payload = _make_payload(query_text, role)

    actual_intent = None
    t_send = time.perf_counter()

    timing = _TimingFields(
        ttft_ms=None,
        end_to_end_ms=None,
        retrieval_ms=None,
        intent_ms=None,
        response_chars=0,
        error=None,
    )

    try:
        async with ws_connect(ws_url, open_timeout=10, ping_interval=None) as ws:
            handshake_raw = await asyncio.wait_for(ws.recv(), timeout=10.0)
            handshake_data = json.loads(handshake_raw)
            if handshake_data.get("type") != "connected":
                raise RuntimeError(f"Unexpected handshake: {handshake_raw!r}")

            # Ignore connection setup time; measurements begin when the benchmark query is sent.
            t_send = time.perf_counter()
            await ws.send(json.dumps(payload))

            ttft_ms = retrieval_ms = intent_ms = None
            response_chars = 0

            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=per_message_timeout)
                msg = json.loads(raw)

                (
                    ttft_ms,
                    intent_ms,
                    retrieval_ms,
                    actual_intent,
                    response_chars,
                    done,
                ) = _classify_ws_message(
                    msg,
                    t_send,
                    ttft_ms,
                    intent_ms,
                    retrieval_ms,
                    actual_intent,
                    response_chars,
                )

                if msg.get("type") == "error":
                    timing.error = msg.get("message", "unknown WS error")
                    break

                if done:
                    timing.end_to_end_ms = (time.perf_counter() - t_send) * 1000
                    break

            timing.ttft_ms = ttft_ms
            timing.retrieval_ms = retrieval_ms
            timing.intent_ms = intent_ms
            timing.response_chars = response_chars

    except Exception as exc:
        timing.end_to_end_ms = (time.perf_counter() - t_send) * 1000
        timing.error = str(exc)

    return _build_measurement(
        run_id,
        query_label,
        query_text,
        complexity,
        expected_intent,
        actual_intent,
        "ws",
        run_index,
        timing,
    )


async def ingest_document(base_url: str, doc_path: str) -> bool:
    """Upload a document to /upload_document so RAG queries have context.
    File reading runs on the thread pool to avoid blocking the event loop."""
    basename = os.path.basename(doc_path)
    print(f"  [ingest] uploading {basename} ...")
    try:
        file_bytes = await asyncio.to_thread(Path(doc_path).read_bytes)
        async with _http_client(total=60.0) as client:
            resp = await client.post(
                f"{base_url}/upload_document",
                files={"file": (basename, file_bytes, "application/octet-stream")},
            )
        resp.raise_for_status()
        print(f"  [ingest] done ({len(file_bytes) // 1024} KB)")
        return True
    except Exception as exc:
        print(f"  [ingest] failed: {exc}")
        return False


async def wait_for_server(
    base_url: str, retries: int = 12, poll_delay: float = 2.0
) -> bool:
    """Poll the server until it responds to /docs or until retries are exhausted."""
    print(f"Waiting for server at {base_url} ...")
    for attempt in range(1, retries + 1):
        try:
            async with _http_client(total=5.0) as client:
                r = await client.get(f"{base_url}/docs")
            if r.status_code < 500:
                print(f"  Server ready (attempt {attempt})")
                return True
        except Exception:
            pass
        await asyncio.sleep(poll_delay)
    print("  Server did not respond in time")
    return False


def _stats(values: list[float]) -> dict:
    """Return mean, std, median, and n for a list of values."""
    mean = statistics.mean(values)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    median = statistics.median(values)
    return {"mean": mean, "std": std, "median": median, "n": len(values)}


def _fmt_stats(values: list[Optional[float]]) -> str:
    """Format a list of values as "mean +/- std  med=median  (n=N)" or "N/A" if empty."""
    v = [x for x in values if x is not None]
    if not v:
        return "N/A"
    if len(v) == 1:
        return f"{v[0]:.0f} ms (n=1)"
    s = _stats(v)
    return f"{s['mean']:.0f} +/- {s['std']:.0f} ms  med={s['median']:.0f}  (n={s['n']})"


def _filter_warm(
    measurements: list[Measurement],
    mode: str,
    transport: str,
    complexity: str,
) -> list[Measurement]:
    """Return only warm runs (run_index >= 2) for the given mode, transport, and complexity."""
    return [
        m
        for m in measurements
        if m.expected_intent == mode
        and m.transport == transport
        and m.complexity == complexity
        and m.error is None
        and not m.is_first_run
    ]


def _ttest_paired(a: list[float], b: list[float]) -> Optional[float]:
    """Paired t-test (ttest_rel). Appropriate because HTTP and WS measurements
    are paired by (query, run_index). Returns p-value or None."""
    if not SCIPY_AVAILABLE or len(a) < 2 or len(b) < 2 or len(a) != len(b):
        return None
    _, p = scipy_stats.ttest_rel(a, b)
    return float(p)


def build_summary(measurements: list[Measurement]) -> dict:
    """Build a nested dict keyed by [mode][transport][complexity] containing
    pre-formatted stat strings for warm runs and first-run observations."""
    from collections import defaultdict

    summary: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))

    for mode in ("CHAT", "RAG", "SQL"):
        for transport in ("http", "ws"):
            for complexity in ("simple", "complex"):
                # All measurements for this benchmark cell, including first runs and failures.
                all_in_cell = [
                    m
                    for m in measurements
                    if m.expected_intent == mode
                    and m.transport == transport
                    and m.complexity == complexity
                ]
                warm = _filter_warm(measurements, mode, transport, complexity)

                # First-run observations are reported separately from pooled warm runs.
                first = [m for m in all_in_cell if m.is_first_run and m.error is None]
                err = [m for m in all_in_cell if m.error is not None]

                summary[mode][transport][complexity] = {
                    "warm": {
                        "ttft": _fmt_stats([m.ttft_ms for m in warm]),
                        "end_to_end": _fmt_stats([m.end_to_end_ms for m in warm]),
                        "retrieval": _fmt_stats(
                            [m.retrieval_ms for m in warm if m.retrieval_ms]
                        ),
                        "intent": _fmt_stats(
                            [m.intent_ms for m in warm if m.intent_ms]
                        ),
                        "resp_chars": _fmt_stats(
                            [float(m.response_chars) for m in warm]
                        ),
                        "n": len(warm),
                    },
                    "first": {
                        "ttft": _fmt_stats([m.ttft_ms for m in first]),
                        "end_to_end": _fmt_stats([m.end_to_end_ms for m in first]),
                        "n": len(first),
                    },
                    "error_count": len(err),
                    "n_total": len(all_in_cell),
                }

    return summary


def _section_raw(measurements: list[Measurement]) -> list[str]:
    """Report every individual measurement in a table."""
    lines = [
        "",
        "TABLE 1: RAW MEASUREMENTS (every run)",
        SEP,
        f"{'Run ID':<32} {'Tr':<4} {'Mode':<5} {'Cx':<7} {'Ri':>2} "
        f"{'TTFT':>8} {'E2E':>8} {'Chars':>6} {'1st':>4} {'IntOK':>5} {'Error':<35}",
        SEP,
    ]

    # Group related runs together for easier visual inspection.
    key = lambda m: (m.expected_intent, m.transport, m.complexity, m.run_index)  # noqa: E731
    for m in sorted(measurements, key=key):
        ttft = f"{m.ttft_ms:.0f}" if m.ttft_ms is not None else "N/A"
        e2e = f"{m.end_to_end_ms:.0f}" if m.end_to_end_ms is not None else "N/A"
        frst = "YES" if m.is_first_run else "-"
        iok = "Y" if m.intent_correct else "N"
        err = (m.error or "")[:33]
        lines.append(
            f"{m.run_id:<32} {m.transport:<4} {m.expected_intent:<5} {m.complexity:<7} "
            f"{m.run_index:>2} {ttft:>8} {e2e:>8} {m.response_chars:>6} "
            f"{frst:>4} {iok:>5} {err:<35}"
        )
    lines.append(SEP)
    return lines


def _section_summary(summary: dict) -> list[str]:
    """Report mean, std, and median for warm runs (run_index >= 2) only."""
    cw = 42
    lines = [
        "",
        "TABLE 2: WARM-RUN SUMMARY  (run_index >= 2)",
        "  mean +/- std  med=median  all values in ms.",
        SEP,
        f"{'Cell':<28} {'TTFT':>{cw}} {'End-to-End':>{cw}} "
        f"{'Intent Lat. (WS only)':>{cw}} {'Resp. Chars':>{cw}}",
        SEP,
    ]
    for mode in ("CHAT", "RAG", "SQL"):
        for transport in ("http", "ws"):
            for complexity in ("simple", "complex"):
                cell = summary.get(mode, {}).get(transport, {}).get(complexity, {})
                warm = cell.get("warm", {})
                label = f"{mode}/{transport.upper()}/{complexity}"
                note = f"  [n={warm.get('n', 0)}, errors={cell.get('error_count', 0)}]"
                lines.append(
                    f"{label:<28} {warm.get('ttft', 'N/A'):>{cw}} "
                    f"{warm.get('end_to_end', 'N/A'):>{cw}} "
                    f"{warm.get('intent', 'N/A'):>{cw}} "
                    f"{warm.get('resp_chars', 'N/A'):>{cw}}{note}"
                )
        lines.append("")
    lines.append(SEP)
    return lines


def _section_first_run(summary: dict) -> list[str]:
    """Report first-run TTFT and end-to-end latency separately from warm runs."""
    lines = [
        "",
        "TABLE 3: FIRST-RUN LATENCY  (run_index == 1 for each query)",
        "  This is the first repetition of each query, not a session-level cold start.",
        "  The model is already loaded (warmup ran before measurements began).",
        "  Reported separately and never pooled with warm runs.",
        SEP,
        f"{'Cell':<28} {'First-Run TTFT':>30} {'First-Run E2E':>30} {'n':>4}",
        SEP,
    ]
    for mode in ("CHAT", "RAG", "SQL"):
        for transport in ("http", "ws"):
            for complexity in ("simple", "complex"):
                cell = summary.get(mode, {}).get(transport, {}).get(complexity, {})
                first = cell.get("first", {})
                label = f"{mode}/{transport.upper()}/{complexity}"
                lines.append(
                    f"{label:<28} {first.get('ttft', 'N/A'):>30} "
                    f"{first.get('end_to_end', 'N/A'):>30} {first.get('n', 0):>4}"
                )
    lines.append(SEP)
    return lines


def _section_reduction(measurements: list[Measurement]) -> list[str]:
    """Report TTFT reduction of WebSocket vs HTTP streaming for warm runs only."""
    lines = [
        "",
        "TABLE 4: TTFT REDUCTION -- HTTP streaming vs WebSocket  (warm runs only)",
        "  Delta = HTTP_mean - WS_mean  (positive means WS is faster).",
        "  Paired t-test (ttest_rel) because HTTP and WS are paired by (query, run_index).",
        SEP,
        f"{'Mode/Complexity':<25} {'HTTP TTFT':>32} {'WS TTFT':>32} "
        f"{'Delta ms':>10} {'%':>7} {'p-value':>10}",
        SEP,
    ]
    for mode in ("CHAT", "RAG", "SQL"):
        for complexity in ("simple", "complex"):
            http_vals = [
                m.ttft_ms
                for m in measurements
                if m.expected_intent == mode
                and m.transport == "http"
                and m.complexity == complexity
                and not m.is_first_run
                and m.error is None
                and m.ttft_ms is not None
            ]
            ws_vals = [
                m.ttft_ms
                for m in measurements
                if m.expected_intent == mode
                and m.transport == "ws"
                and m.complexity == complexity
                and not m.is_first_run
                and m.error is None
                and m.ttft_ms is not None
            ]

            label = f"{mode}/{complexity}"
            http_str = _fmt_stats(http_vals)
            ws_str = _fmt_stats(ws_vals)

            # Compare only matched warm-run observations across transports.
            if (
                len(http_vals) >= 2
                and len(ws_vals) >= 2
                and len(http_vals) == len(ws_vals)
            ):
                delta = statistics.mean(http_vals) - statistics.mean(ws_vals)
                pct = delta / statistics.mean(http_vals) * 100
                p_val = _ttest_paired(http_vals, ws_vals)
                d_str = f"{delta:+.0f}"
                pct_str = f"{pct:+.1f}%"
                p_str = f"{p_val:.3f}" if p_val is not None else "N/A"
            else:
                d_str = pct_str = p_str = "n/a"

            lines.append(
                f"{label:<25} {http_str:>32} {ws_str:>32} "
                f"{d_str:>10} {pct_str:>7} {p_str:>10}"
            )
    lines.append(SEP)
    return lines


def _section_retrieval(summary: dict) -> list[str]:
    """Report RAG retrieval latency, which is only available via WebSocket status events."""
    lines = [
        "",
        "TABLE 5: RAG RETRIEVAL LATENCY  (WebSocket only)",
        "  Measured as time from request send to the 'Generating response' status event.",
        "  HTTP retrieval latency is not available -- no in-band status events on HTTP.",
        SEP,
        f"{'Cell':<28} {'Retrieval Lat. (WS only)':>42}",
        SEP,
    ]
    for complexity in ("simple", "complex"):
        cell = summary.get("RAG", {}).get("ws", {}).get(complexity, {})
        warm = cell.get("warm", {})
        label = f"RAG/WS/{complexity}"
        lines.append(f"{label:<28} {warm.get('retrieval', 'N/A'):>42}")
    lines.append(SEP)
    return lines


def _section_intent(measurements: list[Measurement]) -> list[str]:
    """Report how often the router classified each benchmark query as expected."""
    lines = [
        "",
        "TABLE 6: INTENT ROUTING CONSISTENCY",
        "  Measures whether the router classified each benchmark query as expected.",
        SEP,
        f"{'Mode':<8} {'Total':>10} {'Correct':>10} {'Accuracy':>10}",
        SEP,
    ]
    for mode in ("CHAT", "RAG", "SQL"):
        all_mode = [
            m for m in measurements if m.expected_intent == mode and m.error is None
        ]
        n_total = len(all_mode)
        n_correct = sum(1 for m in all_mode if m.intent_correct)
        acc_str = f"{n_correct / n_total:.1%}" if n_total else "N/A"
        lines.append(f"{mode:<8} {n_total:>10} {n_correct:>10} {acc_str:>10}")

    all_valid = [m for m in measurements if m.error is None]
    n_total = len(all_valid)
    n_correct = sum(1 for m in all_valid if m.intent_correct)
    overall_acc = f"{n_correct / n_total:.1%}" if n_total else "N/A"
    lines += [
        SEP,
        f"{'OVERALL':<8} {n_total:>10} {n_correct:>10} {overall_acc:>10}",
        SEP,
    ]
    return lines


def _section_errors(measurements: list[Measurement]) -> list[str]:
    """List all runs that failed with an error."""
    errors = [m for m in measurements if m.error]
    lines = ["", f"ERRORS: {len(errors)} / {len(measurements)} total runs"]
    for m in errors:
        lines.append(f"  {m.run_id:<40}  {m.error}")
    return lines


def build_report(measurements: list[Measurement], summary: dict) -> str:
    """Assemble all report sections. Prints to stdout and returns as a string."""
    sections = [
        [
            SEP2,
            "  SLM PROJECT -- TTFT BENCHMARK RESULTS",
            f"  Generated : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Total runs: {len(measurements)}",
            SEP2,
        ],
        _section_raw(measurements),
        _section_summary(summary),
        _section_first_run(summary),
        _section_reduction(measurements),
        _section_retrieval(summary),
        _section_intent(measurements),
        _section_errors(measurements),
        [SEP2, "END OF REPORT", SEP2, ""],
    ]

    all_lines: list[str] = []
    for section in sections:
        for line in section:
            all_lines.append(line)
            print(line)

    return "\n".join(all_lines)


def export_csv(summary: dict, path: Path) -> None:
    """Export a CSV file with one row per benchmark cell (mode/transport/complexity)."""
    rows = []
    for mode in ("CHAT", "RAG", "SQL"):
        for transport in ("http", "ws"):
            for complexity in ("simple", "complex"):
                cell = summary.get(mode, {}).get(transport, {}).get(complexity, {})
                warm = cell.get("warm", {})
                first = cell.get("first", {})
                # Flatten nested summary structure into a spreadsheet-friendly format.
                rows.append(
                    {
                        "mode": mode,
                        "transport": transport.upper(),
                        "complexity": complexity,
                        "warm_ttft": warm.get("ttft", "N/A"),
                        "warm_e2e": warm.get("end_to_end", "N/A"),
                        "warm_intent_ms": warm.get("intent", "N/A"),
                        "warm_retrieval_ms": warm.get("retrieval", "N/A"),
                        "warm_resp_chars": warm.get("resp_chars", "N/A"),
                        "first_run_ttft": first.get("ttft", "N/A"),
                        "first_run_e2e": first.get("end_to_end", "N/A"),
                        "n_warm": warm.get("n", 0),
                        "n_first": first.get("n", 0),
                        "error_count": cell.get("error_count", 0),
                        "n_total": cell.get("n_total", 0),
                    }
                )

    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)
    print(f"  CSV saved: {path}")


async def _write_text(path: Path, text: str) -> None:
    """Write a text file asynchronously, ensuring UTF-8 encoding."""
    await asyncio.to_thread(path.write_text, text, encoding="utf-8")


async def _write_json(path: Path, obj: object) -> None:
    """Write a JSON file asynchronously, ensuring UTF-8 encoding and pretty-printing."""
    text = json.dumps(obj, indent=2, ensure_ascii=False)
    await asyncio.to_thread(path.write_text, text, encoding="utf-8")


def _print_status(m: Measurement) -> None:
    """Print a single-line status update for a completed measurement."""
    if m.error:
        print(f"ERROR: {m.error[:55]}")
        return
    first_tag = " [first-run]" if m.is_first_run else ""
    intent_tag = "Y" if m.intent_correct else f"N(got {m.actual_intent})"
    ttft_str = f"{m.ttft_ms:.0f} ms" if m.ttft_ms is not None else "N/A"
    e2e_str = f"{m.end_to_end_ms:.0f} ms" if m.end_to_end_ms is not None else "N/A"
    print(f"TTFT={ttft_str:<10} E2E={e2e_str:<10} intent={intent_tag}{first_tag}")


async def _run_pair(
    q_label: str,
    q_text: str,
    complexity: str,
    expected_intent: str,
    run_index: int,
    base_url: str,
    role: str,
    skip_ws: bool,
    delay: float,
) -> list[Measurement]:
    """Fire HTTP and WS back-to-back for the same (query, run_index).
    Alternates which transport goes first to eliminate ordering bias."""
    results: list[Measurement] = []

    http_first = run_index % 2 == 1
    if skip_ws:
        transports = ["http"]
    elif http_first:
        transports = ["http", "ws"]
    else:
        transports = ["ws", "http"]

    for transport in transports:
        label = f"{q_label}/{transport}/run{run_index}"
        print(f"    {label:<45} ... ", end="", flush=True)

        if transport == "http":
            m = await measure_http(
                q_label, q_text, complexity, expected_intent, run_index, base_url, role
            )
        else:
            m = await measure_ws(
                q_label, q_text, complexity, expected_intent, run_index, base_url, role
            )

        results.append(m)
        _print_status(m)
        await asyncio.sleep(delay)

    return results


async def _setup_rag(
    base_url: str, modes: list[str], rag_doc: str, delay: float
) -> None:
    """Upload a document once so all RAG queries share identical context if the mode is enabled and the document exists."""
    if "RAG" not in modes or not rag_doc:
        return
    doc_path = os.path.expanduser(rag_doc)

    # 
    if os.path.exists(doc_path):
        await ingest_document(base_url, doc_path)
        await asyncio.sleep(delay)
    else:
        print(f"  [warn] RAG doc not found: {doc_path} -- RAG queries may fail")


async def _run_warmup(base_url: str, n_warmup: int, delay: float) -> None:
    """Run unrecorded warmup queries to avoid measuring model-load time in run 1."""
    if n_warmup <= 0:
        return
    print(f"\nWarmup ({n_warmup} x HTTP, not recorded) ...")
    for i in range(n_warmup):
        print(f"  warmup {i + 1}/{n_warmup} ...", end=" ", flush=True)
        m = await measure_http("warmup", WARMUP_QUERY, "simple", "CHAT", 0, base_url)
        print(f"done ({m.end_to_end_ms:.0f} ms)")
        await asyncio.sleep(delay)
    print()


async def run_benchmark(args: argparse.Namespace) -> list[Measurement]:
    """Run the full benchmark for the given command-line arguments."""
    base_url = f"http://{args.host}:{args.port}"
    modes = [m.upper() for m in args.modes]

    if not await wait_for_server(base_url):
        print("Aborting -- server not reachable.")
        sys.exit(1)

    await _setup_rag(base_url, modes, args.rag_doc, args.delay)
    await _run_warmup(base_url, args.warmup, args.delay)

    measurements: list[Measurement] = []

    # Execute every query across all requested repetitions and transports.
    for mode in modes:
        queries = ALL_QUERIES.get(mode)
        if not queries:
            print(f"[warn] unknown mode '{mode}', skipping")
            continue

        n_transports = 1 if args.skip_ws else 2
        print(f"\n{'=' * 60}")
        print(
            f"  MODE: {mode}  ({len(queries)} queries x {args.n} runs x {n_transports} transport(s))"
        )
        print(f"{'=' * 60}")

        for q_label, q_text, complexity, expected_intent in queries:
            for run_index in range(1, args.n + 1):
                pair = await _run_pair(
                    q_label,
                    q_text,
                    complexity,
                    expected_intent,
                    run_index,
                    base_url,
                    "Standard_User",
                    args.skip_ws,
                    args.delay,
                )
                measurements.extend(pair)

    return measurements


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments for the benchmark script."""
    p = argparse.ArgumentParser(
        description="TTFT benchmark -- SLM project (Test 4)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", default=8000, type=int)
    p.add_argument(
        "--n",
        default=10,
        type=int,
        help="Runs per (query x transport) cell. Run 1 is the first-run observation.",
    )
    p.add_argument(
        "--modes",
        default=["CHAT", "RAG", "SQL"],
        nargs="+",
        choices=["CHAT", "RAG", "SQL"],
    )
    p.add_argument(
        "--warmup",
        default=2,
        type=int,
        help="Unrecorded HTTP warmup queries. Set 0 to include model-load in run 1.",
    )
    p.add_argument(
        "--delay",
        default=2.0,
        type=float,
        help="Seconds between consecutive measurements.",
    )
    p.add_argument("--skip-ws", action="store_true", help="HTTP transport only.")
    p.add_argument("--rag-doc", default="data/uploads/enterprise_ai (1).pdf")
    p.add_argument("--out-dir", default="results")
    return p.parse_args()


async def main() -> None:
    """Run the benchmark and generate a report."""
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(SEP2)
    print("  SLM TTFT BENCHMARK")
    print(f"  Server   : http://{args.host}:{args.port}")
    print(f"  Modes    : {args.modes}")
    print(f"  N        : {args.n}  (run 1 = first-run observation per query)")
    print(f"  Warmup   : {args.warmup} (not recorded)")
    print(f"  Delay    : {args.delay} s")
    print(f"  RAG doc  : {args.rag_doc}")
    print(f"  Skip WS  : {args.skip_ws}")
    print(f"  Output   : {out_dir}/")
    print(SEP2)

    measurements = await run_benchmark(args)

    # Persist raw measurements so analyses can be reproduced later.
    raw_path = out_dir / f"ttft_raw_{timestamp}.json"
    await _write_json(
        raw_path,
        {
            "meta": {
                "timestamp": timestamp,
                "n": args.n,
                "modes": args.modes,
                "warmup": args.warmup,
                "delay_s": args.delay,
                "skip_ws": args.skip_ws,
                "host": args.host,
                "port": args.port,
                "first_run_definition": "run_index == 1 for each query (not session-level cold start)",
            },
            "measurements": [asdict(m) for m in measurements],
        },
    )
    print(f"\n  Raw JSON  : {raw_path}")

    summary = build_summary(measurements)
    report_text = build_report(measurements, summary)

    txt_path = out_dir / f"ttft_summary_{timestamp}.txt"
    await _write_text(txt_path, report_text)
    print(f"  Report    : {txt_path}")

    csv_path = out_dir / f"ttft_summary_{timestamp}.csv"
    await asyncio.to_thread(export_csv, summary, csv_path)

    print(f"\nDone. {len(measurements)} measurements saved to {out_dir}/")


if __name__ == "__main__":
    asyncio.run(main())
