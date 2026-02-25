#!/usr/bin/env python3
"""
Benchmark: compare latency of Python vs Rust vector services.

Usage:
    python benchmark.py [--rounds 50] [--warmup 3] [--endpoint semantic-search]
    python benchmark.py --local                   # Benchmark local run-local.sh instance

Endpoints:
    semantic-search  POST /semantic-search  (CLAP text→vector + DuckDB)
    sample           GET  /tracks           (random sample from DuckDB)
    text-search      GET  /search           (metadata text search)

Reports p50, p95, p99 latencies for each service.

    python benchmark.py --cold-start          # Measure cold start only (no warmup)
"""

import argparse
import json
import random
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import requests

PYTHON_URL = "https://cloud-crate-vector-403961692263.us-central1.run.app"
RUST_URL = "https://cloud-crate-vector-rs-403961692263.us-central1.run.app"
LOCAL_URL = "http://localhost:8000"

# Diverse queries to avoid caching effects
SEMANTIC_QUERIES = [
    "warm analog synths with lo-fi drums",
    "aggressive distorted guitar riffs",
    "calm piano with soft strings",
    "funky bass groove with wah guitar",
    "ambient drone with field recordings",
    "fast breakbeat jungle drums",
    "smooth jazz saxophone solo",
    "ethereal female vocals with reverb",
    "heavy metal double bass drumming",
    "tropical house with steel drums",
    "dark minimal techno kick",
    "acoustic fingerpicking folk guitar",
    "glitchy IDM with granular textures",
    "orchestral swells and brass fanfare",
    "boom bap hip hop beat with vinyl crackle",
    "shoegaze wall of distorted guitars and reverb",
    "deep dubstep wobble bass",
    "bossa nova nylon guitar",
    "psychedelic sitar with tape delay",
    "chip tune 8-bit arpeggios",
    "post-punk bass and drum machine",
    "gospel choir harmonies",
    "industrial noise with metal percussion",
    "afrobeat polyrhythmic drums",
    "dreamy chillwave synth pads",
    "country pedal steel guitar",
    "acid house 303 squelch",
    "classical string quartet allegro",
    "reggae dub delay and spring reverb",
    "trap hi-hats and 808 sub bass",
]

TEXT_SEARCH_QUERIES = [
    {"artist": "Radiohead"},
    {"title": "Blue"},
    {"artist": "Boards of Canada"},
    {"album": "OK Computer"},
    {"title": "Sun"},
    {"artist": "Aphex Twin"},
    {"album": "Homogenic"},
    {"title": "Rain"},
    {"artist": "Four Tet"},
    {"album": "Vespertine"},
]


def percentile(data: list[float], p: int) -> float:
    """Calculate the p-th percentile of a list."""
    n = len(data)
    if n == 0:
        return 0.0
    sorted_data = sorted(data)
    k = (n - 1) * p / 100
    f = int(k)
    c = f + 1 if f + 1 < n else f
    d = k - f
    return sorted_data[f] + d * (sorted_data[c] - sorted_data[f])


def make_request(url: str, endpoint: str, timeout: int = 30) -> float:
    """Send a single request and return latency in ms."""
    start = time.perf_counter()

    if endpoint == "semantic-search":
        query = random.choice(SEMANTIC_QUERIES)
        resp = requests.post(
            f"{url}/semantic-search",
            json={"query": query, "limit": 10, "source": "library", "enhance": False},
            timeout=timeout,
        )
    elif endpoint == "sample":
        resp = requests.get(
            f"{url}/tracks",
            params={"limit": 20, "random": "true"},
            timeout=timeout,
        )
    elif endpoint == "text-search":
        params = random.choice(TEXT_SEARCH_QUERIES)
        resp = requests.get(
            f"{url}/search",
            params={**params, "limit": 10},
            timeout=timeout,
        )
    else:
        raise ValueError(f"Unknown endpoint: {endpoint}")

    elapsed_ms = (time.perf_counter() - start) * 1000
    resp.raise_for_status()
    return elapsed_ms


def warmup(url: str, endpoint: str, rounds: int, label: str):
    """Send warmup requests to avoid cold-start skew."""
    print(f"  Warming up {label} ({rounds} requests)...", end=" ", flush=True)
    for _ in range(rounds):
        try:
            make_request(url, endpoint)
        except Exception as e:
            print(f"\n    Warning: warmup request failed: {e}")
    print("done")


def benchmark(url: str, endpoint: str, rounds: int, label: str) -> list[float]:
    """Run benchmark rounds sequentially and return latencies."""
    latencies = []
    errors = 0
    print(f"  Benchmarking {label} ({rounds} requests)...", end=" ", flush=True)
    for i in range(rounds):
        try:
            ms = make_request(url, endpoint)
            latencies.append(ms)
        except Exception as e:
            errors += 1
            if errors <= 3:
                print(f"\n    Error on request {i+1}: {e}")
    print("done")
    if errors:
        print(f"    ({errors} errors out of {rounds} requests)")
    return latencies


def report(label: str, latencies: list[float]):
    """Print percentile report for a set of latencies."""
    if not latencies:
        print(f"  {label}: no successful requests")
        return
    p50 = percentile(latencies, 50)
    p95 = percentile(latencies, 95)
    p99 = percentile(latencies, 99)
    avg = statistics.mean(latencies)
    mn = min(latencies)
    mx = max(latencies)
    print(f"  {label}:")
    print(f"    p50:  {p50:>8.1f} ms")
    print(f"    p95:  {p95:>8.1f} ms")
    print(f"    p99:  {p99:>8.1f} ms")
    print(f"    mean: {avg:>8.1f} ms")
    print(f"    min:  {mn:>8.1f} ms")
    print(f"    max:  {mx:>8.1f} ms")
    print(f"    n:    {len(latencies)}")


def main():
    parser = argparse.ArgumentParser(description="Benchmark Python vs Rust vector services")
    parser.add_argument("--rounds", type=int, default=50, help="Number of benchmark requests per service (default: 50)")
    parser.add_argument("--warmup", type=int, default=3, help="Number of warmup requests per service (default: 3)")
    parser.add_argument("--endpoint", default="semantic-search", choices=["semantic-search", "sample", "text-search"],
                        help="Endpoint to benchmark (default: semantic-search)")
    parser.add_argument("--python-url", default=PYTHON_URL, help="Python service URL")
    parser.add_argument("--rust-url", default=RUST_URL, help="Rust service URL")
    parser.add_argument("--only", choices=["python", "rust"], help="Only benchmark one service")
    parser.add_argument("--local", action="store_true",
                        help="Benchmark local Rust service at localhost:8000 (from run-local.sh)")
    parser.add_argument("--local-url", default=LOCAL_URL, help="Local service URL (default: http://localhost:8000)")
    parser.add_argument("--cold-start", action="store_true",
                        help="Measure cold start latency (first request, no warmup). "
                             "Uses a 120s timeout to account for container spin-up.")
    args = parser.parse_args()

    services = []
    if args.local:
        services.append(("Local", args.local_url))
    else:
        if args.only != "rust":
            services.append(("Python", args.python_url))
        if args.only != "python":
            services.append(("Rust", args.rust_url))

    if args.cold_start:
        run_cold_start(services, args.endpoint)
    else:
        run_warm_benchmark(services, args.endpoint, args.rounds, args.warmup)


def run_cold_start(services: list[tuple[str, str]], endpoint: str):
    """Measure cold start: hit both services simultaneously, report first-request latency."""
    print(f"Cold Start Benchmark: {endpoint}")
    print("  Sending first request to each service in parallel...")
    print("  (Using 120s timeout to account for container spin-up)")
    print()

    cold_results = {}

    def cold_request(label, url):
        try:
            ms = make_request(url, endpoint, timeout=120)
            return label, ms, None
        except Exception as e:
            return label, None, str(e)

    with ThreadPoolExecutor(max_workers=len(services)) as pool:
        futures = [pool.submit(cold_request, label, url) for label, url in services]
        for f in futures:
            label, ms, err = f.result()
            if err:
                cold_results[label] = None
                print(f"  {label}: FAILED - {err}")
            else:
                cold_results[label] = ms
                print(f"  {label}: {ms:>8.1f} ms")

    print()
    print("=" * 50)
    print("Cold Start Results:")
    print("=" * 50)
    for label, _ in services:
        ms = cold_results.get(label)
        if ms is not None:
            print(f"  {label}: {ms:>8.1f} ms")
        else:
            print(f"  {label}: FAILED")

    if len(cold_results) == 2 and "Python" in cold_results and "Rust" in cold_results and all(v is not None for v in cold_results.values()):
        py_ms = cold_results["Python"]
        rs_ms = cold_results["Rust"]
        diff = abs(py_ms - rs_ms)
        faster = "Python" if py_ms < rs_ms else "Rust"
        print(f"\n  Delta: {diff:.0f} ms faster ({faster})")
        print(f"  Ratio: {max(py_ms, rs_ms) / min(py_ms, rs_ms):.2f}x")


def run_warm_benchmark(services: list[tuple[str, str]], endpoint: str, rounds: int, warmup_rounds: int):
    """Standard warm benchmark with percentile reporting."""
    print(f"Benchmark: {endpoint}")
    print(f"  Rounds: {rounds}, Warmup: {warmup_rounds}")
    print()

    # Warmup both services in parallel to trigger cold starts simultaneously
    print("Warmup phase:")
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(warmup, url, endpoint, warmup_rounds, label)
            for label, url in services
        ]
        for f in futures:
            f.result()
    print()

    # Benchmark sequentially per service to avoid contention
    results = {}
    print("Benchmark phase:")
    for label, url in services:
        results[label] = benchmark(url, endpoint, rounds, label)
    print()

    # Report
    print("=" * 50)
    print("Results:")
    print("=" * 50)
    for label, _ in services:
        report(label, results[label])
    print()

    # Comparison
    if len(results) == 2 and "Python" in results and "Rust" in results:
        py_lat = results["Python"]
        rs_lat = results["Rust"]
        if py_lat and rs_lat:
            py_p50 = percentile(py_lat, 50)
            rs_p50 = percentile(rs_lat, 50)
            if py_p50 > 0:
                diff = ((rs_p50 - py_p50) / py_p50) * 100
                faster = "Rust" if rs_p50 < py_p50 else "Python"
                print(f"  p50 delta: {abs(diff):.1f}% faster ({faster})")


if __name__ == "__main__":
    main()
