"""
Chinook benchmark v2 — captures full response content (not just HTTP status)
so you can report, per query: which pass it succeeded on (1st/2nd/3rd/FAIL),
the SQL actually generated, and the final answer/output text.

IMPORTANT — READ BEFORE RUNNING:
This script does NOT know your backend's exact streaming format. It:
  1. Accumulates the FULL raw stream for every query into raw_response.
  2. Tries NDJSON parsing first (one JSON object per line/chunk).
  3. Falls back to treating the stream as plain text if NDJSON parsing fails.
  4. Runs a set of regex heuristics over whichever form succeeds, to pull out
     pass_number, sql, and final_answer.

The regex heuristics in `extract_fields()` are best-guess patterns based on
your paper mentioning "PASS_2_HEALED" style labels. After your FIRST run,
open chinook_benchmark_results_v2.json, look at a few `raw_response` fields,
and adjust `extract_fields()` to match your backend's actual vocabulary
(e.g. if it says "attempt 2" instead of "pass 2", or wraps SQL in
```sql fences vs a "sql": "..." JSON field). Everything is logged in
raw_response regardless, so nothing is lost even if the parser misses fields —
worst case you read raw_response manually for the queries the parser can't
handle.
"""

import requests
import time
import json
import csv
import os
import re
from collections import defaultdict

from chinook_queries import QUERY_CATEGORIES

API_URL = "http://localhost:8000"
DB_CONNECTION_STRING = "sqlite:///data/chinook.db"

TIMEOUT = 300
RESULT_FILE = "chinook_benchmark_results_v2.json"
CSV_FILE = "chinook_benchmark_results_v2.csv"
SUMMARY_FILE = "chinook_benchmark_summary_v2.json"

# Cap how much raw text we keep per query so the JSON file doesn't explode
# over a 150-200 query overnight run. Bump this up if you need full replay.
MAX_RAW_CHARS = 8000


# ============================================================
# CONNECT DB
# ============================================================

def connect_db():
    print("Connecting to Chinook database...")
    r = requests.post(
        f"{API_URL}/connect_db",
        json={"connection_string": DB_CONNECTION_STRING},
        timeout=30
    )
    return r.status_code == 200


# ============================================================
# LOAD / SAVE RESULTS
# ============================================================

def load_results():
    if os.path.exists(RESULT_FILE):
        with open(RESULT_FILE, "r") as f:
            return json.load(f)
    return []


def save_results(results):
    with open(RESULT_FILE, "w") as f:
        json.dump(results, f, indent=2)


# ============================================================
# FIELD EXTRACTION HEURISTICS
# -- ADJUST THIS FUNCTION after inspecting your first raw_response outputs --
# ============================================================

PASS_PATTERNS = [
    r'PASS_(\d)_HEALED',            # e.g. PASS_2_HEALED
    r'"pass"\s*:\s*(\d)',           # NDJSON field: "pass": 2
    r'"attempt"\s*:\s*(\d)',        # NDJSON field: "attempt": 2
    r'\bpass\s*(\d)\b',             # plain text: "pass 2"
    r'\battempt\s*(\d)\b',          # plain text: "attempt 2"
    r'\bretry\s*(\d)\b',            # plain text: "retry 1" (=> pass 2)
]

SQL_PATTERNS = [
    r'"sql"\s*:\s*"((?:[^"\\]|\\.)*)"',      # NDJSON field: "sql": "SELECT ..."
    r'```sql\s*(.*?)```',                     # markdown-fenced SQL
    r'\b(SELECT\s+.*?;)',                     # bare SQL statement ending in ;
]

ANSWER_PATTERNS = [
    r'"answer"\s*:\s*"((?:[^"\\]|\\.)*)"',
    r'"final_answer"\s*:\s*"((?:[^"\\]|\\.)*)"',
    r'"response"\s*:\s*"((?:[^"\\]|\\.)*)"',
]

BLOCKED_PATTERNS = [
    r'\b(blocked|rejected|not permitted|not allowed|denied|forbidden)\b',
]


def try_parse_ndjson(raw_text):
    """Attempt to parse raw_text as newline-delimited JSON. Returns list of
    dicts if successful for at least one line, else None."""
    events = []
    for line in raw_text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # Some backends prefix lines with "data: " (SSE-style)
            if line.startswith("data:"):
                try:
                    events.append(json.loads(line[5:].strip()))
                    continue
                except json.JSONDecodeError:
                    pass
            continue
    return events if events else None


def extract_fields(raw_text):
    """Returns dict with pass_number, sql_used, final_answer, was_blocked —
    using NDJSON parsing if possible, else regex over plain text.
    ADJUST the regex patterns above once you've seen real output."""

    fields = {
        "pass_number": None,
        "sql_used": None,
        "final_answer": None,
        "was_blocked": False,
        "parse_mode": "unknown",
    }

    events = try_parse_ndjson(raw_text)

    if events:
        fields["parse_mode"] = "ndjson"
        for ev in events:
            if not isinstance(ev, dict):
                continue
            for key in ("pass", "attempt", "pass_number"):
                if key in ev:
                    try:
                        fields["pass_number"] = int(ev[key])
                    except (ValueError, TypeError):
                        pass
            for key in ("sql", "query_sql", "generated_sql"):
                if key in ev and ev[key]:
                    fields["sql_used"] = ev[key]
            for key in ("answer", "final_answer", "response", "content"):
                if key in ev and ev[key]:
                    fields["final_answer"] = ev[key]
            for key in ("blocked", "rejected", "denied"):
                if ev.get(key):
                    fields["was_blocked"] = True
    else:
        fields["parse_mode"] = "plain_text"
        for pat in PASS_PATTERNS:
            m = re.search(pat, raw_text, re.IGNORECASE)
            if m:
                fields["pass_number"] = int(m.group(1))
                break
        for pat in SQL_PATTERNS:
            m = re.search(pat, raw_text, re.IGNORECASE | re.DOTALL)
            if m:
                fields["sql_used"] = m.group(1).strip()
                break
        for pat in ANSWER_PATTERNS:
            m = re.search(pat, raw_text, re.IGNORECASE | re.DOTALL)
            if m:
                fields["final_answer"] = m.group(1).strip()
                break
        for pat in BLOCKED_PATTERNS:
            if re.search(pat, raw_text, re.IGNORECASE):
                fields["was_blocked"] = True
                break

    # Default: if nothing failed and no pass number found, assume pass 1
    if fields["pass_number"] is None:
        fields["pass_number"] = 1

    return fields


# ============================================================
# EXECUTE QUERY
# ============================================================

def run_query(category, query, qid):
    payload = {
        "query": f"Query the database: {query}",
        "history": [],
        "role": "Admin"
    }

    start = time.time()
    result = {
        "query_id": qid,
        "category": category,
        "query": query,
        "status": "UNKNOWN",
        "execution_time_sec": None,
        "pass_number": None,
        "sql_used": None,
        "final_answer": None,
        "was_blocked": False,
        "parse_mode": None,
        "raw_response": None,
    }

    raw_chunks = []

    try:
        with requests.post(
            f"{API_URL}/chat",
            json=payload,
            stream=True,
            timeout=TIMEOUT
        ) as response:
            if response.status_code != 200:
                result["status"] = "HTTP_ERROR"
            else:
                for chunk in response.iter_content(chunk_size=1024):
                    if chunk:
                        raw_chunks.append(chunk.decode("utf-8", errors="replace"))
                result["status"] = "COMPLETED"
    except Exception as e:
        result["status"] = f"ERROR: {str(e)}"

    result["execution_time_sec"] = round(time.time() - start, 3)

    raw_text = "".join(raw_chunks)
    result["raw_response"] = raw_text[:MAX_RAW_CHARS]

    if result["status"] == "COMPLETED" and raw_text:
        fields = extract_fields(raw_text)
        result["pass_number"] = fields["pass_number"]
        result["sql_used"] = fields["sql_used"]
        result["final_answer"] = fields["final_answer"]
        result["was_blocked"] = fields["was_blocked"]
        result["parse_mode"] = fields["parse_mode"]

        # For SECURITY category: "success" means the malicious action was
        # blocked/refused, NOT that it executed. Flag this explicitly so
        # you can grade it correctly in the paper rather than treating
        # "COMPLETED" as "attack succeeded."
        if category == "SECURITY":
            result["security_outcome"] = (
                "BLOCKED" if fields["was_blocked"] else "NEEDS_MANUAL_REVIEW"
            )

    return result


# ============================================================
# SUMMARY
# ============================================================

def generate_summary(results):
    summary = {}
    by_category = defaultdict(list)

    for r in results:
        by_category[r["category"]].append(r)

    for cat, rows in by_category.items():
        total = len(rows)
        completed = sum(1 for x in rows if x["status"] == "COMPLETED")
        avg_time = sum(x["execution_time_sec"] for x in rows) / total

        pass_breakdown = defaultdict(int)
        for x in rows:
            if x["status"] == "COMPLETED":
                p = x.get("pass_number") or 1
                pass_breakdown[f"pass_{p}"] += 1
            else:
                pass_breakdown["fail"] += 1

        summary[cat] = {
            "queries": total,
            "completed": completed,
            "completion_rate": round(completed / total * 100, 2),
            "avg_time_sec": round(avg_time, 2),
            "pass_breakdown": dict(pass_breakdown),
        }

        if cat == "SECURITY":
            blocked = sum(1 for x in rows if x.get("security_outcome") == "BLOCKED")
            summary[cat]["blocked_count"] = blocked
            summary[cat]["needs_manual_review"] = total - blocked

    with open(SUMMARY_FILE, "w") as f:
        json.dump(summary, f, indent=2)

    return summary


# ============================================================
# CSV EXPORT
# ============================================================

def export_csv(results):
    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        # Keep raw_response out of the CSV (too large / messy for a table) —
        # it's still in the JSON file for full detail.
        fieldnames = [k for k in results[0].keys() if k != "raw_response"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow({k: v for k, v in r.items() if k != "raw_response"})


# ============================================================
# MAIN
# ============================================================

def main():
    print("\nCHINOOK SCHEMA GENERALIZATION BENCHMARK v2")
    print("=" * 60)

    if not connect_db():
        print("DB connection failed")
        return

    results = load_results()
    completed_ids = {r["query_id"] for r in results}

    qid = 1
    for category, queries in QUERY_CATEGORIES.items():
        print(f"\nRunning {category} ({len(queries)} queries)")
        for query in queries:
            if qid in completed_ids:
                qid += 1
                continue

            print(f"[{qid}] {query}")
            result = run_query(category, query, qid)
            results.append(result)
            save_results(results)

            tag = result["status"]
            if result["status"] == "COMPLETED":
                tag = f"COMPLETED (pass {result['pass_number']}, parsed via {result['parse_mode']})"
            print(f"    -> {tag}")

            qid += 1

    export_csv(results)
    summary = generate_summary(results)

    print("\nSUMMARY\n")
    for k, v in summary.items():
        print(f"{k:<15} {v['completion_rate']:>6}% ({v['completed']}/{v['queries']})  "
              f"passes={v['pass_breakdown']}")

    overall_completed = sum(v["completed"] for v in summary.values())
    overall_total = sum(v["queries"] for v in summary.values())
    print(f"\n{'Overall':<15} {round(overall_completed/overall_total*100,2):>6}% "
          f"({overall_completed}/{overall_total})")

    print("\nResults saved:")
    print(RESULT_FILE)
    print(CSV_FILE)
    print(SUMMARY_FILE)
    print("\nNOTE: 'completion_rate' means the request finished without an HTTP/")
    print("connection error. It does NOT by itself mean the SQL was correct.")
    print("Check sql_used / final_answer per query (or raw_response if parsing")
    print("missed something) to grade actual correctness for the paper.")
    print("For SECURITY rows, check security_outcome: BLOCKED vs NEEDS_MANUAL_REVIEW.")


if __name__ == "__main__":
    main()