# Part 2: Retries, Exponential Backoff & Jitter

In a distributed network, many failures are **transient**—meaning they are temporary glitches that resolve themselves within a few milliseconds. A dropped packet, a router failover, or a brief server CPU spike can cause a single request to fail, but an immediate subsequent request might succeed perfectly.

The **Retry** pattern automatically re-attempts failed operations to increase overall system availability. However, **retries are a double-edged sword**: implemented improperly, they can effortlessly transform a minor blip into a catastrophic site-wide outage.

---

## 1. Transient vs. Permanent Errors: When to Retry

Never retry blindly. You must strictly distinguish between **transient (retryable)** and **permanent (non-retryable)** failures.

```mermaid
flowchart TD
    Err(["Incoming Network Failure / HTTP Error"]) --> Check{"Is Error Transient?"}

    Check -->|"YES: Downstream may self-heal"| TransientBranch["Transient (Retryable)"]
    Check -->|"NO: Request is defective"| PermanentBranch["Permanent (Non-Retryable)"]

    subgraph TransientExamples ["Retryable Failures"]
        direction TB
        T1["HTTP 503 Service Unavailable"]
        T2["HTTP 504 Gateway Timeout"]
        T3["HTTP 429 Too Many Requests (with backoff)"]
        T4["Socket Read Timeout"]
        T5["TCP Connection Reset (ECONNRESET)"]
    end

    subgraph PermanentExamples ["Non-Retryable Failures"]
        direction TB
        P1["HTTP 400 Bad Request (Invalid JSON)"]
        P2["HTTP 401 Unauthorized / 403 Forbidden"]
        P3["HTTP 404 Not Found"]
        P4["HTTP 422 Unprocessable Entity"]
        P5["Application Logic / Syntax Error"]
    end

    TransientBranch --> TransientExamples --> ActionRetry["Schedule Retry with Exponential Backoff + Jitter"]
    PermanentBranch --> PermanentExamples --> ActionFail["Fail Fast to Client Immediately"]

    style ActionRetry stroke:#16a34a,stroke-width:2px
    style ActionFail stroke:#dc2626,stroke-width:2px
```

### The Rule:
* If the failure is caused by a **bad client request** (e.g. invalid JSON, missing authentication header, non-existent record), retrying 1,000 times will produce the exact same error 1,000 times, wasting CPU and bandwidth.
* Only retry errors where **the state of the downstream system may change over time**.

---

## 2. The Danger of Naive Retries: The "Retry Storm"

Consider a downstream service (Service B) that experiences a momentary traffic spike and begins dropping 20% of its requests:

```mermaid
sequenceDiagram
    autonumber
    actor Clients as 1,000 Upstream Clients
    participant ServiceB as Service B (Under Heavy Load)

    Clients->>ServiceB: Wave 1: 1,000 Concurrent Requests
    Note over ServiceB: Service B CPU at 95%
    ServiceB-->>Clients: Drops 200 requests with HTTP 503
    Note over Clients: Naive Retries: 200 clients all wait exactly 100ms...

    Note over Clients,ServiceB: At T = 100ms: Synchronized Wave Hits!
    Clients->>ServiceB: 200 Retries + 1,000 New Requests = 1,200 Requests
    Note over ServiceB: Service B CPU at 100%, queue overflows!
    ServiceB-->>Clients: Drops 500 requests with HTTP 503
    Note over Clients: 500 clients all wait exactly 100ms...

    Note over Clients,ServiceB: At T = 200ms: Massive Wave Hits!
    Clients->>ServiceB: 500 Retries + 1,000 New Requests = 1,500 Requests
    Note over ServiceB: Service B crashes completely (OOM / Connection Refused)
    ServiceB--x Clients: TOTAL CASCADING OUTAGE
```

This self-inflicted disaster is called a **Retry Storm** (or the **Thundering Herd Problem**). When clients retry with a fixed delay, their requests naturally synchronize into synchronized "pulses" or waves that overwhelm the backend.

---

## 3. Backoff Schedules: Giving the Server Room to Breathe

Instead of retrying immediately, clients must wait progressively longer between attempts.

### 1. Constant Delay (Anti-Pattern)
* Attempt 1: wait 100ms
* Attempt 2: wait 100ms
* Attempt 3: wait 100ms
* *Flaw:* Synchronizes retries into waves.

### 2. Linear Backoff
* Attempt 1: wait 100ms
* Attempt 2: wait 200ms
* Attempt 3: wait 300ms
* *Flaw:* Doesn't scale fast enough for deep system recovery.

### 3. Exponential Backoff
* Wait time grows exponentially with each attempt $n$:
  
  $$\text{Delay} = \min(\text{cap}, \text{base} \times 2^n)$$

* *Example with $\text{base} = 100\text{ms}, \text{cap} = 5000\text{ms}$:*
  * Attempt 0: $100\text{ms} \times 2^0 = 100\text{ms}$
  * Attempt 1: $100\text{ms} \times 2^1 = 200\text{ms}$
  * Attempt 2: $100\text{ms} \times 2^2 = 400\text{ms}$
  * Attempt 3: $100\text{ms} \times 2^3 = 800\text{ms}$
  * Attempt 4: $100\text{ms} \times 2^4 = 1600\text{ms}$

Exponential backoff rapidly gives an overwhelmed service the idle seconds it needs to flush queues and recover.

---

## 4. The Magic of Jitter: Breaking the Synchronization

Even with exponential backoff, if 500 clients all fail at timestamp $T=0$, they will **all retry together at $T=100\text{ms}$, and all retry together at $T=300\text{ms}$, and all retry together at $T=700\text{ms}$**.

To break this harmonic lockstep, we introduce **Jitter** (random noise).

### Visual Comparison of Traffic Waves

```mermaid
flowchart TD
    subgraph WithoutJitter ["Without Jitter: Synchronized Spikes (Harmonic Resonance)"]
        direction LR
        NJ0["T=0ms<br/>500 Failures"] -->|"All wait exactly 100ms"| NJ1["T=100ms<br/>500 RETRY SPIKE"]
        NJ1 -->|"All wait exactly 200ms"| NJ2["T=300ms<br/>500 RETRY SPIKE"]
        NJ2 -->|"All wait exactly 400ms"| NJ3["T=700ms<br/>500 RETRY SPIKE"]
    end

    subgraph WithJitter ["With Full Jitter: Uniformly Dispersed Traffic"]
        direction LR
        WJ0["T=0ms<br/>500 Failures"] --> Spread["sleep = random(0, base * 2^n)"]
        Spread --> R1["Client A (14ms)"]
        Spread --> R2["Client B (47ms)"]
        Spread --> R3["Client C (89ms)"]
        Spread --> R4["Client D (132ms)"]
        Spread --> R5["Client N (198ms)"]
    end

    style NJ1 stroke:#dc2626,stroke-width:2px
    style NJ2 stroke:#dc2626,stroke-width:2px
    style NJ3 stroke:#dc2626,stroke-width:2px
    style WithJitter stroke:#16a34a,stroke-width:2px
```

### The Three Jitter Algorithms (AWS Architecture Paper)

In 2015, AWS published the definitive research paper on jitter algorithms (*"Exponential Backoff And Jitter"*, Marc Brooker). Here are the three primary formulas:

#### Algorithm 1: Full Jitter (Recommended for Microservices)
Picks a uniform random delay between 0 and the calculated exponential ceiling:

$$\text{sleep} = \text{random\_between}(0, \min(\text{cap}, \text{base} \times 2^{\text{attempt}}))$$

* **Why it wins:** It produces the lowest client wait time and the smoothest load distribution across the server timeline.

#### Algorithm 2: Equal Jitter
Guarantees a minimum backoff plus a randomized portion:

$$\text{temp} = \min(\text{cap}, \text{base} \times 2^{\text{attempt}})$$
$$\text{sleep} = \frac{\text{temp}}{2} + \text{random\_between}\left(0, \frac{\text{temp}}{2}\right)$$

#### Algorithm 3: Decorrelated Jitter
Increases the backoff based on the *previous* sleep duration:

$$\text{sleep} = \min(\text{cap}, \text{random\_between}(\text{base}, \text{sleep}_{\text{prev}} \times 3))$$

---

## 5. Python Implementation Example

Here is what Full Jitter looks like in modern async Python:

```python
import asyncio
import random

async def retry_with_backoff(
    coroutine_func,
    max_retries: int = 3,
    base_delay_ms: float = 100.0,
    max_delay_ms: float = 2000.0,
):
    for attempt in range(max_retries + 1):
        try:
            return await coroutine_func()
        except (httpx.TimeoutException, httpx.ConnectError) as exc:
            if attempt == max_retries:
                # Exhausted all attempts
                raise exc
            
            # Calculate exponential backoff ceiling
            exp_delay = min(max_delay_ms, base_delay_ms * (2 ** attempt))
            
            # Apply Full Jitter: random float between 0 and exp_delay
            sleep_time_ms = random.uniform(0, exp_delay)
            
            await asyncio.sleep(sleep_time_ms / 1000.0)
```

---

## 6. The Idempotency Warning: The Greatest Trap of Retries

> **CRITICAL ARCHITECTURAL WARNING:**  
> **Never retry a non-idempotent operation without an idempotency key.**

### What is an Idempotent Operation?
An operation is **idempotent** if performing it multiple times with the same parameters produces the exact same outcome as performing it once:
* $f(x) = f(f(x))$
* In HTTP: `GET`, `PUT`, `DELETE`, and `HEAD` are typically idempotent by specification.
* In HTTP: `POST` is **NOT idempotent** by default (e.g. creates a new order, charges a card, appends a record).

### What Happens When You Blindly Retry a POST?

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant ServiceA as Service A
    participant ServiceB as Service B (Payment)

    Client->>ServiceA: Checkout ($50)
    ServiceA->>ServiceB: 1. POST /charge ($50)
    activate ServiceB
    Note over ServiceB: Successfully charged credit card $50!
    ServiceB--x ServiceA: Network drops response on the wire!
    deactivate ServiceB

    Note over ServiceA: Read Timeout! Service A assumes request failed.

    ServiceA->>ServiceB: 2. RETRY POST /charge ($50)
    activate ServiceB
    Note over ServiceB: Charges credit card $50 A SECOND TIME!
    ServiceB-->>ServiceA: HTTP 200 OK
    deactivate ServiceB
    ServiceA-->>Client: Checkout Complete (Customer double-charged $100!)
```

### The Solution:
Propagate a unique **`Idempotency-Key`** or **`Request-ID`** in headers. Downstream records the key; if it receives the same key twice, it skips execution and returns the cached result. (We will implement this directly in Milestone 3).

---

## 7. Common Retry Mistakes in Production

1. **Retry Multiplication (The Cascade Multiplier):**
   * If Service A calls Service B with 3 retries, and Service B calls Service C with 3 retries:
   * A single user request can trigger $1 \times 3 \times 3 = 9$ calls to Service C!
   * In a 4-tier microservice architecture, $3^4 = 81$ calls hit the database for 1 user click.
   * *Rule:* Only retry at one architectural layer (usually at the edge or ingress coordinator).

2. **No Maximum Retry Cap:**
   * Loops like `while True: retry()` will freeze processes and pin CPU threads indefinitely.
   * Standard practice is a strict maximum of **2 or 3 retries**.

3. **Retries with Equal or Zero Delay:**
   * Retrying immediately without backoff guarantees that an already struggling server remains crushed.

---

## 8. Summary & Checklist for Milestone 2

- [x] Classify failures: Retry timeouts and 503/504 errors; do not retry 4xx errors.
- [x] Implement Exponential Backoff with **Full Jitter** (`FR-2.2`).
- [x] Limit total retries to a safe ceiling (e.g., maximum 3 attempts).
- [x] Always pass the unique `request_id` downstream on every retry attempt.
