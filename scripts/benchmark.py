#!/usr/bin/env python3
"""
benchmark.py -- Performance benchmark script for the AI Voice Sales Agent.

Measures:
  - Cold start: time to import all modules + instantiate Conversation.
  - Warm start: re-instantiate (modules already imported).
  - RAG retrieval: 100 queries against real KB -> p50, p95, p99 latency.
  - RAG cache effectiveness: 50 identical queries -> cache hit rate.
  - Memory absorption: 1000 turns through CustomerMemory.absorb_turn().
  - CRM write: 10 writes to temp leads_template.xlsx copy.
  - Peak memory: tracemalloc peak during a full 4-turn simulated call.

Outputs logs/benchmark_report.json and prints a formatted table.
"""

import json
import shutil
import sys
import time
import tracemalloc
from pathlib import Path
from unittest.mock import MagicMock, patch

# Configure sys.path so we can import agent and crm modules
BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE_DIR / "agent"))
sys.path.insert(0, str(BASE_DIR / "crm"))
sys.path.insert(0, str(BASE_DIR))

# Mock llama_cpp module to avoid ModuleNotFoundError or loading it
mock_llama_cpp = MagicMock()
sys.modules["llama_cpp"] = mock_llama_cpp


def measure_cold_start() -> float:
    """Measure import time + first conversation instantiation."""
    # We must measure this in a subprocess to get a true cold start,
    # but doing it via dynamic import of the heavy modules here is a good approximation.
    start = time.perf_counter()
    import conversation

    lead = {"lead_id": "L001", "name": "Jane"}
    conversation.Conversation(
        lead=lead,
        company_name="Acme Co",
        caller_purpose="testing",
        knowledge_base="## Section\nInfo",
        llm_config={"provider": "ollama", "max_history_turns": 4},
        rag_config={"top_k": 2, "min_score": 0.01},
    )
    return time.perf_counter() - start


def main():
    print("=" * 60)
    print("AI Voice Sales Agent -- Performance Benchmark")
    print("=" * 60)

    # 1. Cold Start
    print("Measuring Cold Start...")
    cold_start_time = measure_cold_start()
    print(f"Cold Start: {cold_start_time:.3f}s")

    # Now imports are warm, import modules normally
    import conversation
    import excel_crm
    import knowledge_retriever
    import llm_client
    from memory import CustomerMemory

    # 2. Warm Start (re-instantiate)
    print("Measuring Warm Start...")
    start = time.perf_counter()
    lead = {"lead_id": "L001", "name": "Jane"}
    conversation.Conversation(
        lead=lead,
        company_name="Acme Co",
        caller_purpose="testing",
        knowledge_base="## Section\nInfo",
        llm_config={"provider": "ollama", "max_history_turns": 4},
        rag_config={"top_k": 2, "min_score": 0.01},
    )
    warm_start_time = time.perf_counter() - start
    print(f"Warm Start: {warm_start_time:.6f}s")

    # Load real KB
    kb_path = BASE_DIR / "config" / "knowledge_base.md"
    if kb_path.exists():
        with open(kb_path, encoding="utf-8") as f:
            kb_text = f.read()
    else:
        kb_text = "## Pricing\nPlan starter is $19/mo.\n\n## Integrations\nSlack and Google."

    # 3. RAG Retrieval Latency
    print("Measuring RAG Retrieval Latency (100 queries)...")
    retriever = knowledge_retriever.KnowledgeRetriever(kb_text, cache_size=32)
    queries = [
        "What is the pricing?",
        "Do you integrate with slack?",
        "Is there a free trial?",
        "How do I setup?",
        "Who founded the company?",
    ] * 20  # 100 queries

    latencies = []
    for q in queries:
        start_ret = time.perf_counter()
        retriever.retrieve(q, top_k=2)
        latencies.append(time.perf_counter() - start_ret)

    latencies.sort()
    p50 = latencies[int(len(latencies) * 0.50)]
    p95 = latencies[int(len(latencies) * 0.95)]
    p99 = latencies[int(len(latencies) * 0.99)]
    avg_rag = sum(latencies) / len(latencies)

    print(f"RAG Latency (s) -- Avg: {avg_rag:.6f}, p50: {p50:.6f}, p95: {p95:.6f}, p99: {p99:.6f}")

    # 4. RAG Cache Effectiveness
    print("Measuring RAG Cache Hit Latency (50 identical queries)...")
    cache_latencies = []
    # Query it once to populate cache
    retriever.retrieve("What is the pricing?", top_k=2)
    for _ in range(50):
        start_cache = time.perf_counter()
        retriever.retrieve("What is the pricing?", top_k=2)
        cache_latencies.append(time.perf_counter() - start_cache)

    avg_cache_hit = sum(cache_latencies) / len(cache_latencies)
    print(f"RAG Cache Hit Latency (s) -- Avg: {avg_cache_hit:.6f}")

    # 5. Memory Absorption
    print("Measuring Memory Absorption (1000 turns)...")
    mem = CustomerMemory()
    start_mem = time.perf_counter()
    for i in range(500):
        mem.absorb_turn("user", f"We have {i} people on our sales team and pricing is important.")
        mem.absorb_turn("assistant", "We booked a meeting on Wednesday at 2pm.")
    mem_duration = time.perf_counter() - start_mem
    print(f"Memory Absorption (1000 turns): {mem_duration:.3f}s")

    # 6. CRM Write Latency
    print("Measuring CRM Write Latency (10 writes)...")
    template_xlsx = BASE_DIR / "crm" / "leads_template.xlsx"
    temp_dir = BASE_DIR / "logs" / "benchmark_temp"
    temp_dir.mkdir(parents=True, exist_ok=True)
    temp_excel = temp_dir / "leads.xlsx"

    crm_latencies = []
    if template_xlsx.exists():
        for _ in range(10):
            shutil.copy2(str(template_xlsx), str(temp_excel))
            start_crm = time.perf_counter()
            excel_crm.update_lead(
                str(temp_excel),
                "L001",
                {"status": "Booked", "meeting_datetime": "2026-07-15 10:00"},
            )
            crm_latencies.append(time.perf_counter() - start_crm)
        avg_crm = sum(crm_latencies) / len(crm_latencies)
        print(f"CRM Write Latency (10 writes) -- Avg: {avg_crm:.3f}s")
    else:
        avg_crm = 0.0
        print("leads_template.xlsx not found -- skipping CRM benchmark.")

    # Cleanup temp CRM dir
    if temp_dir.exists():
        shutil.rmtree(temp_dir)

    # 7. Peak Memory during full simulated call
    print("Measuring Peak Memory during simulated 4-turn call...")
    tracemalloc.start()

    # Mock LLM to return simple conversation results and JSON extraction
    mock_usage = llm_client.LLMUsage(prompt_tokens=50, completion_tokens=20, inference_ms=100)
    with (
        patch("llm_client.chat_with_usage", return_value=("Hello, how can I help?", mock_usage)),
        patch("llm_client.chat", return_value='{"status": "Booked", "qualification": "Hot"}'),
    ):
        lead_data = {"lead_id": "L001", "name": "Jane"}
        sim_convo = conversation.Conversation(
            lead=lead_data,
            company_name="Acme Co",
            caller_purpose="testing",
            knowledge_base=kb_text,
            llm_config={"provider": "ollama", "max_history_turns": 4},
            rag_config={"top_k": 2, "min_score": 0.01},
        )
        sim_convo.agent_opening_line()
        sim_convo.respond_to("What is the cost of your starter plan?")
        sim_convo.respond_to("Do you integrate with slack?")
        sim_convo.respond_to("Yes, let's book a walkthrough on Friday at 3pm.")
        sim_convo.extract_result()

    _, peak_memory = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    peak_memory_mb = peak_memory / (1024 * 1024)
    print(f"Peak Memory: {peak_memory_mb:.2f} MB")

    # Generate benchmark_report.json
    report = {
        "benchmark_timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "cold_start_seconds": round(cold_start_time, 3),
        "warm_start_seconds": round(warm_start_time, 6),
        "rag_retrieval_latency": {
            "avg_seconds": round(avg_rag, 6),
            "p50_seconds": round(p50, 6),
            "p95_seconds": round(p95, 6),
            "p99_seconds": round(p99, 6),
        },
        "rag_cache_hit_latency_avg_seconds": round(avg_cache_hit, 6),
        "memory_absorption_1000_turns_seconds": round(mem_duration, 3),
        "crm_write_latency_avg_seconds": round(avg_crm, 3),
        "peak_memory_mb": round(peak_memory_mb, 2),
    }

    report_dir = BASE_DIR / "logs"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / "benchmark_report.json"
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print("\n" + "=" * 60)
    print(f"Benchmark report successfully written to {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
