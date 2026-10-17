#!/usr/bin/env python3
"""Milestone 1 Verification Script: Synchronous Baseline & Fault Injection

Usage:
    python scripts/verify_m1.py [service_a_url]
Default:
    http://localhost:8000
"""

import asyncio
import sys
import time
from typing import Any

import httpx


async def run_scenario(
    client: httpx.AsyncClient,
    base_url: str,
    name: str,
    latency_ms: int,
    failure_rate_pct: float,
    count: int = 1,
) -> list[dict[str, Any]]:
    print(f"\n{'='*70}")
    print(f"▶ SCENARIO: {name}")
    print(f"  Config: latency={latency_ms}ms, failure_rate={failure_rate_pct}%, runs={count}")
    print(f"{'='*70}")

    results = []
    for i in range(count):
        start = time.perf_counter()
        try:
            resp = await client.post(
                f"{base_url}/trigger",
                json={"latency_ms": latency_ms, "failure_rate_pct": failure_rate_pct},
                timeout=30.0,
            )
            wall_time_ms = (time.perf_counter() - start) * 1000.0
            data = resp.json()
            rtt_reported = data.get("round_trip_duration_ms", -1)
            req_id = data.get("request_id", "N/A")[:8]
            status_str = data.get("status", "unknown")

            results.append({
                "run": i + 1,
                "http_status": resp.status_code,
                "status": status_str,
                "rtt_ms": rtt_reported,
                "wall_ms": round(wall_time_ms, 2),
                "req_id": req_id,
            })
            print(
                f"  [{i+1:2d}/{count:2d}] HTTP {resp.status_code} | "
                f"Status: {status_str:<16} | "
                f"Service A RTT: {rtt_reported:7.2f}ms | "
                f"Client Wall: {wall_time_ms:7.2f}ms | ID: {req_id}..."
            )
        except (httpx.HTTPError, ValueError) as e:
            wall_time_ms = (time.perf_counter() - start) * 1000.0
            print(f"  [{i+1:2d}/{count:2d}] ERROR: {e} ({wall_time_ms:.2f}ms)")
            results.append({"run": i + 1, "error": str(e), "wall_ms": wall_time_ms})

    return results


async def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    print(f"Starting Milestone 1 Verification against Service A at: {base_url}")

    async with httpx.AsyncClient() as client:
        # Check health first
        try:
            resp = await client.get(f"{base_url}/health", timeout=3.0)
            if resp.status_code != 200:
                print(f"Health check failed with status {resp.status_code}: {resp.text}")
                sys.exit(1)
            print("Service A is UP and healthy!")
        except (httpx.HTTPError, OSError) as exc:
            print(f"Cannot connect to Service A at {base_url}: {exc}")
            print("Tip: Make sure `docker compose up` or local uvicorn is running.")
            sys.exit(1)

        # 1. Baseline: 50ms latency, 0% failure
        await run_scenario(
            client,
            base_url,
            name="1. Baseline Execution (50ms simulated delay, 0% failure)",
            latency_ms=50,
            failure_rate_pct=0.0,
            count=3,
        )

        # 2. High Latency: 1000ms delay, 0% failure
        await run_scenario(
            client,
            base_url,
            name="2. Tail Latency Injection (1000ms simulated delay, 0% failure)",
            latency_ms=1000,
            failure_rate_pct=0.0,
            count=2,
        )

        # 3. Guaranteed Downstream Failure: 100% failure rate
        await run_scenario(
            client,
            base_url,
            name="3. Guaranteed Failure Injection (100% failure rate)",
            latency_ms=50,
            failure_rate_pct=100.0,
            count=3,
        )

        # 4. Probabilistic Failure: 50% failure rate across 10 requests
        results = await run_scenario(
            client,
            base_url,
            name="4. Probabilistic Failure Distribution (50% failure rate over 10 requests)",
            latency_ms=30,
            failure_rate_pct=50.0,
            count=10,
        )

        successes = sum(1 for r in results if r.get("http_status") == 200)
        failures = sum(1 for r in results if r.get("http_status") == 502)
        print(f"\n{'-'*70}")
        print(f"Distribution Summary: {successes} Successes (200 OK), {failures} Failures (502 Bad Gateway)")
        print(f"{'-'*70}")
        print("\n Milestone 1 Verification Complete!")


if __name__ == "__main__":
    asyncio.run(main())
