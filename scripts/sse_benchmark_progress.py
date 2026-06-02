import json
import math
import time
import urllib.request
from statistics import mean

URL = "http://localhost:8000/investigation/run"
RUNS = 10
CASES = [
    ("deep", "Investigate the biggest operational risks for lidar-ingestion-service and recommend mitigations with evidence."),
    ("direct", "Hi there"),
]


def percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    xs = sorted(values)
    if len(xs) == 1:
        return xs[0]
    idx = math.ceil((pct / 100.0) * len(xs)) - 1
    idx = max(0, min(idx, len(xs) - 1))
    return xs[idx]


def sse_request(query: str, case_name: str, run_idx: int):
    payload = json.dumps({"query": query, "history": [], "session_context": ""}).encode("utf-8")
    req = urllib.request.Request(URL, data=payload, headers={"Content-Type": "application/json"})

    t0 = time.perf_counter()
    events = []

    with urllib.request.urlopen(req, timeout=300) as resp:
        event_name = None
        data_lines = []
        for raw in resp:
            line = raw.decode("utf-8", errors="replace").rstrip("\n")
            if line.startswith("event:"):
                event_name = line.split(":", 1)[1].strip()
            elif line.startswith("data:"):
                data_lines.append(line.split(":", 1)[1].lstrip())
            elif line == "":
                if event_name:
                    payload_text = "\n".join(data_lines) if data_lines else "{}"
                    try:
                        data = json.loads(payload_text)
                    except Exception:
                        data = {"_raw": payload_text}
                    t_rel = time.perf_counter() - t0
                    events.append((event_name, data, t_rel))
                    if event_name == "step-update":
                        node = data.get("node", "unknown")
                        agent = data.get("agent", "unknown")
                        summary = str(data.get("summary", ""))[:80]
                        print(
                            f"[{case_name}] run {run_idx}/{RUNS} step {node}/{agent} at {t_rel:.2f}s | {summary}",
                            flush=True,
                        )
                    elif event_name == "investigation-complete":
                        print(
                            f"[{case_name}] run {run_idx}/{RUNS} event investigation-complete at {t_rel:.2f}s",
                            flush=True,
                        )
                    if event_name == "investigation-complete":
                        break
                event_name = None
                data_lines = []

    return events


def run_case(case_name: str, query: str):
    totals = []
    node_done_samples: dict[str, list[float]] = {}

    print(f"\n===== CASE: {case_name} ({RUNS} runs) =====", flush=True)
    for i in range(1, RUNS + 1):
        t_run = time.perf_counter()
        print(f"[{case_name}] run {i}/{RUNS} starting...", flush=True)
        evs = sse_request(query, case_name, i)
        total = evs[-1][2] if evs else 0.0
        totals.append(total)

        seen_node_done = {}
        for name, data, t_rel in evs:
            if name != "step-update":
                continue
            node = data.get("node", "unknown")
            if node not in seen_node_done:
                seen_node_done[node] = t_rel

        for node, t in seen_node_done.items():
            node_done_samples.setdefault(node, []).append(t)

        print(
            f"[{case_name}] run {i}/{RUNS} done: total={total:.2f}s "
            f"(wall={time.perf_counter() - t_run:.2f}s) nodes={','.join(sorted(seen_node_done.keys()))}",
            flush=True,
        )

    print(f"\n--- SUMMARY {case_name} ---", flush=True)
    print("totals:", ", ".join(f"{t:.2f}" for t in totals), flush=True)
    print(f"avg={mean(totals):.2f}s p50={percentile(totals, 50):.2f}s p95={percentile(totals, 95):.2f}s", flush=True)
    print("node completion p50/p95:", flush=True)
    for node, samples in sorted(node_done_samples.items(), key=lambda kv: mean(kv[1])):
        print(
            f"  {node:<16} avg={mean(samples):.2f}s p50={percentile(samples, 50):.2f}s p95={percentile(samples, 95):.2f}s n={len(samples)}",
            flush=True,
        )


if __name__ == "__main__":
    overall_start = time.perf_counter()
    for case_name, query in CASES:
        run_case(case_name, query)
    print(f"\nAll benchmarks completed in {time.perf_counter() - overall_start:.2f}s", flush=True)
"""
--- SUMMARY deep ---
totals: 47.13, 43.58, 39.78, 38.68, 40.99, 39.06, 39.15, 40.55, 44.13, 39.65
avg=41.27s p50=39.78s p95=47.13s
node completion p50/p95:
  query_analyzer   avg=10.95s p50=10.72s p95=11.73s n=10
  shared_retrieve  avg=12.08s p50=10.78s p95=16.93s n=10
  evaluate         avg=12.08s p50=10.78s p95=16.93s n=10
  risk_agent       avg=27.96s p50=26.84s p95=33.41s n=10
  synthesize       avg=41.27s p50=39.78s p95=47.13s n=10

--- SUMMARY direct ---
totals: 18.41, 5.73, 5.69, 5.55, 5.75, 6.15, 5.98, 5.72, 5.45, 5.66
avg=7.01s p50=5.72s p95=18.41s
node completion p50/p95:
  query_analyzer   avg=4.83s p50=4.25s p95=10.07s n=10
  synthesize       avg=7.01s p50=5.72s p95=18.41s n=10
"""