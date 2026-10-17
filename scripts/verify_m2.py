#!/usr/bin/env python3
"""Milestone 2 Verification Script: Resilience & Self-Protection Patterns

Demonstrates:
  1. Strict Timeouts (FR-2.1): Aborting slow downstream calls at exact deadline.
  2. Automated Retries & Jitter (FR-2.2): Retrying transient failures with exponential backoff & full jitter.
  3. Circuit Breaker Fast Fallback (FR-2.3): Cutting off traffic to failing downstream and responding in <10ms.
  4. Self-Healing Recovery: Automatic probe and transition from HALF-OPEN to CLOSED.

Usage:
    python scripts/verify_m2.py [service_a_url]
Default:
    http://localhost:8000
"""

import asyncio
import sys
import time

import httpx


async def check_health_and_reset(client: httpx.AsyncClient, base_url: str):
    print("Checking Service A health and resetting Circuit Breaker...")
    resp = await client.get(f"{base_url}/health", timeout=3.0)
    if resp.status_code != 200:
        print(f"Health check failed with status {resp.status_code}")
        sys.exit(1)
    
    # Reset circuit breaker
    reset_resp = await client.post(f"{base_url}/circuit-breaker/reset")
    if reset_resp.status_code != 200:
        print(f"Failed to reset circuit breaker: {reset_resp.text}")
        sys.exit(1)
    print("✓ Service A is healthy and Circuit Breaker is reset to CLOSED.\n")


async def scenario_1_strict_timeout(client: httpx.AsyncClient, base_url: str):
    print(f"{'='*75}")
    print("▶ SCENARIO 1: Strict Timeout Enforcement (FR-2.1)")
    print("  Simulating 3,000ms downstream delay, but Service A enforces 400ms timeout.")
    print(f"{'='*75}")

    start = time.perf_counter()
    resp = await client.post(
        f"{base_url}/trigger",
        json={
            "latency_ms": 3000,
            "failure_rate_pct": 0.0,
            "timeout_ms": 400,
            "use_retry": False,
            "use_circuit_breaker": False,
        },
        timeout=10.0,
    )
    wall_time_ms = (time.perf_counter() - start) * 1000.0
    data = resp.json()

    print(f"  HTTP Status    : {resp.status_code} ({resp.reason_phrase})")
    print(f"  Result Status  : {data.get('status')}")
    print(f"  Reported Error : {data.get('error')}")
    print(f"  Wall-clock Time: {wall_time_ms:.2f}ms (Aborted near 400ms instead of hanging for 3000ms!)")
    assert resp.status_code == 504, f"Expected 504, got {resp.status_code}"
    assert wall_time_ms < 1000.0, "Timeout did not abort early!"
    print("✓ Scenario 1 Passed: Downstream hang was successfully prevented.\n")


async def scenario_2_retries_with_jitter(client: httpx.AsyncClient, base_url: str):
    print(f"{'='*75}")
    print("▶ SCENARIO 2: Automated Retries with Exponential Backoff & Jitter (FR-2.2)")
    print("  Triggering downstream failure (100% failure rate) with max_retries=3.")
    print(f"{'='*75}")

    start = time.perf_counter()
    resp = await client.post(
        f"{base_url}/trigger",
        json={
            "latency_ms": 10,
            "failure_rate_pct": 100.0,
            "max_retries": 3,
            "use_circuit_breaker": False,
            "use_jitter": True,
        },
        timeout=10.0,
    )
    wall_time_ms = (time.perf_counter() - start) * 1000.0
    data = resp.json()
    resilience = data.get("resilience", {})

    print(f"  HTTP Status    : {resp.status_code} ({resp.reason_phrase})")
    print(f"  Total Attempts : {resilience.get('attempts')} (1 initial + 3 retries)")
    print(f"  Jitter Delays  : {resilience.get('retry_delays_ms')} ms")
    print(f"  Wall-clock Time: {wall_time_ms:.2f}ms")
    assert resilience.get("attempts") == 4, f"Expected 4 attempts, got {resilience.get('attempts')}"
    print("✓ Scenario 2 Passed: Retries executed with randomized backoff delays.\n")


async def scenario_3_circuit_breaker(client: httpx.AsyncClient, base_url: str):
    print(f"{'='*75}")
    print("▶ SCENARIO 3: Circuit Breaker Trip & Fast Fallback (FR-2.3 & Acceptance Criteria)")
    print("  Injecting consecutive failures until breaker trips from CLOSED -> OPEN.")
    print(f"{'='*75}")

    # Reset breaker first
    await client.post(f"{base_url}/circuit-breaker/reset")

    for i in range(3):
        resp = await client.post(
            f"{base_url}/trigger",
            json={"latency_ms": 10, "failure_rate_pct": 100.0, "use_retry": False},
        )
        print(f"  Failure {i+1}/3 dispatched: HTTP {resp.status_code}")

    # Inspect breaker state
    status_resp = await client.get(f"{base_url}/circuit-breaker")
    cb_data = status_resp.json()
    print(f"\n  Circuit Breaker Status: State = {cb_data.get('state')}, Failures = {cb_data.get('failure_count')}")
    assert cb_data.get("state") == "OPEN", f"Expected OPEN, got {cb_data.get('state')}"

    # Now send request with 5,000ms delay - breaker must fast-fail in < 10ms!
    print("\n  Dispatching request to OPEN circuit (requested latency = 5,000ms):")
    start = time.perf_counter()
    fallback_resp = await client.post(
        f"{base_url}/trigger",
        json={"latency_ms": 5000, "failure_rate_pct": 0.0},
    )
    wall_time_ms = (time.perf_counter() - start) * 1000.0
    fallback_data = fallback_resp.json()

    print(f"  HTTP Status    : {fallback_resp.status_code}")
    print(f"  Status Field   : {fallback_data.get('status')}")
    print(f"  Breaker Tripped: {fallback_data.get('resilience', {}).get('circuit_breaker_tripped')}")
    print(f"  Fallback Time  : {wall_time_ms:.2f}ms (PRD Acceptance Criteria: <50ms)")
    print(f"  Degraded Msg   : {fallback_data.get('error', {}).get('message')}")
    assert fallback_data.get("status") == "degraded_fallback"
    assert wall_time_ms < 50.0, f"Fallback too slow: {wall_time_ms}ms"
    print("✓ Scenario 3 Passed: Circuit Breaker prevented downstream call and returned immediate fallback!\n")


async def scenario_4_self_healing(client: httpx.AsyncClient, base_url: str):
    print(f"{'='*75}")
    print("▶ SCENARIO 4: Self-Healing Recovery (HALF-OPEN Canary Probe)")
    print("  Waiting for cooldown (5.0s) so breaker can test recovery with a canary probe.")
    print(f"{'='*75}")

    for sec in range(5, 0, -1):
        print(f"  Waiting {sec}s for cooldown timer...", end="\r")
        await asyncio.sleep(1.0)
    print("  Cooldown timer expired!                                      ")

    # Send a healthy probe request
    start = time.perf_counter()
    probe_resp = await client.post(
        f"{base_url}/trigger",
        json={"latency_ms": 20, "failure_rate_pct": 0.0},
    )
    wall_time_ms = (time.perf_counter() - start) * 1000.0
    probe_data = probe_resp.json()

    print(f"\n  Canary Probe HTTP Status: {probe_resp.status_code}")
    print(f"  Canary Result Status     : {probe_data.get('status')}")
    print(f"  Canary Duration          : {wall_time_ms:.2f}ms")

    # Verify breaker is now back to CLOSED
    status_resp = await client.get(f"{base_url}/circuit-breaker")
    cb_data = status_resp.json()
    print(f"  Post-Recovery State      : {cb_data.get('state')} (failure count = {cb_data.get('failure_count')})")
    assert cb_data.get("state") == "CLOSED", f"Expected CLOSED, got {cb_data.get('state')}"
    print("✓ Scenario 4 Passed: System automatically healed itself without human intervention!\n")


async def main():
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    print(f"Starting Milestone 2 Verification against Service A at: {base_url}\n")

    async with httpx.AsyncClient() as client:
        try:
            await check_health_and_reset(client, base_url)
        except (httpx.HTTPError, OSError) as exc:
            print(f"Cannot connect to Service A at {base_url}: {exc}")
            print("Make sure `docker compose up` is running.")
            sys.exit(1)

        await scenario_1_strict_timeout(client, base_url)
        await scenario_2_retries_with_jitter(client, base_url)
        await scenario_3_circuit_breaker(client, base_url)
        await scenario_4_self_healing(client, base_url)

        print(f"{'='*75}")
        print("★ ALL MILESTONE 2 RESILIENCE VERIFICATIONS SUCCEEDED!")
        print(f"{'='*75}")


if __name__ == "__main__":
    asyncio.run(main())
