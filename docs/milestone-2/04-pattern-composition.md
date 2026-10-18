# Part 4: Pattern Composition & Request Lifecycle

Now that we have explored **Strict Timeouts**, **Retries with Jitter**, and **Circuit Breakers** individually, we must address the most critical architectural question:

> **How do these three patterns compose together, and in what exact order should they execute?**

Getting the nesting order wrong is one of the most common distributed systems mistakes.

---

## 1. The "Russian Doll" (Onion) Composition Model

The three patterns must wrap the downstream network call like concentric layers of an onion:

```mermaid
flowchart TD
    Req(["Client Request"]) --> L1

    subgraph OnionModel ["The Onion Composition Architecture"]
        subgraph L1 ["🛡️ Layer 1: Circuit Breaker (Outermost Guard - Amber)"]
            CBCheck{"Is Circuit OPEN?"}
            FastFailResp["Return Instant Fallback\n(under 5ms, Zero Network I/O)"]
            CBCheck -->|"YES (Tripped)"| FastFailResp
            
            subgraph L2 ["🔄 Layer 2: Retry with Backoff & Jitter (Middle Coordinator - Blue)"]
                RetryCoordinator["Retry Coordinator (1..N attempts)"]
                BackoffWait["Sleep with Exponential Backoff + Full Jitter"]
                
                subgraph L3 ["⏱️ Layer 3: Strict Timeout (Innermost Guard - Purple)"]
                    DeadlineTimer["Per-Attempt Timeout Deadline (e.g. 500ms)"]
                    SocketCall["HTTP Socket POST /work"]
                end
            end
        end
    end

    CBCheck -->|"NO (Closed/Half-Open)"| RetryCoordinator
    RetryCoordinator --> DeadlineTimer --> SocketCall
    SocketCall -->|"Transient Failure / Timeout"| BackoffWait --> RetryCoordinator
    SocketCall -->|"HTTP 200 OK"| SuccessResp(["Return Success to Client"])
    FastFailResp --> FailResp(["Return Degraded Fallback to Client"])

    %% Layer Subgraph Styling (Distinct Colors)
    style L1 fill:#78350f,stroke:#f59e0b,stroke-width:3px,color:#ffffff
    style L2 fill:#1e3a8a,stroke:#3b82f6,stroke-width:3px,color:#ffffff
    style L3 fill:#4c1d95,stroke:#8b5cf6,stroke-width:3px,color:#ffffff

    %% Inner Node Styling
    style CBCheck fill:#92400e,stroke:#fbbf24,stroke-width:2px,color:#ffffff
    style FastFailResp fill:#b45309,stroke:#fcd34d,stroke-width:2px,color:#ffffff
    style RetryCoordinator fill:#1d4ed8,stroke:#60a5fa,stroke-width:2px,color:#ffffff
    style BackoffWait fill:#2563eb,stroke:#93c5fd,stroke-width:2px,color:#ffffff
    style DeadlineTimer fill:#6d28d9,stroke:#a78bfa,stroke-width:2px,color:#ffffff
    style SocketCall fill:#7c3aed,stroke:#c4b5fd,stroke-width:2px,color:#ffffff

    %% Terminal Nodes
    style Req fill:#334155,stroke:#94a3b8,stroke-width:2px,color:#ffffff
    style SuccessResp fill:#14532d,stroke:#4ade80,stroke-width:2px,color:#ffffff
    style FailResp fill:#7f1d1d,stroke:#f87171,stroke-width:2px,color:#ffffff
```

---

## 2. Why the Order of Execution Matters

### Why Circuit Breaker Must Be on the OUTSIDE:
* If the Circuit Breaker is `OPEN`, **we want zero network calls and zero retry loops**.
* If you placed the Retry loop outside the Circuit Breaker:
  * The caller would retry an already-tripped circuit breaker 3 times in a row, wasting CPU and delaying the fallback response.
* **Rule:** Circuit Breaker acts as the outermost gatekeeper. If the gate is closed, nobody enters the retry loop.

### Why Timeout Must Be INSIDE Each Retry Attempt:
* A timeout must apply to **each individual HTTP attempt**, not across the entire retry lifecycle.
* *Example:* If you allow 3 attempts and set a per-attempt timeout of `500ms`:
  * Attempt 1 times out at 500ms $\rightarrow$ retry.
  * Attempt 2 times out at 500ms $\rightarrow$ retry.
  * Attempt 3 succeeds in 120ms $\rightarrow$ success!
* If you placed a single global timeout outside the retry loop, a slow first attempt would consume the entire time budget, leaving zero time for retries.

---

## 3. The 4 Operational Scenarios (Sequence Diagrams)

### Scenario 1: The Happy Path (Downstream is Healthy)

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant A as Service A (Coordinator)
    participant CB as Circuit Breaker (CLOSED)
    participant Retry as Retry Coordinator
    participant B as Service B (Worker)

    Client->>A: POST /trigger
    activate A
    A->>CB: can_execute()?
    CB-->>A: True (Allowed)
    A->>Retry: execute_with_retry()
    activate Retry
    Retry->>B: Attempt 1 (POST /work, timeout=500ms)
    activate B
    B-->>Retry: HTTP 200 OK (took 40ms)
    deactivate B
    Retry-->>A: WorkResponse(status="completed")
    deactivate Retry
    A->>CB: record_success()
    A-->>Client: HTTP 200 OK (Total RTT: 42ms)
    deactivate A
```

---

### Scenario 2: Transient Blip (Recovered by Retry + Jitter)

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant A as Service A (Coordinator)
    participant CB as Circuit Breaker (CLOSED)
    participant Retry as Retry Coordinator
    participant B as Service B (Worker)

    Client->>A: POST /trigger
    activate A
    A->>CB: can_execute()?
    CB-->>A: True (Allowed)
    A->>Retry: execute_with_retry()
    activate Retry
    
    Retry->>B: Attempt 1: POST /work (timeout=500ms)
    activate B
    B-->>Retry: HTTP 500 (Random Transient Blip)
    deactivate B
    
    Note over Retry: Transient error caught!<br/>Sleep 120ms (Exponential Backoff + Full Jitter)
    
    Retry->>B: Attempt 2: POST /work (timeout=500ms)
    activate B
    B-->>Retry: HTTP 200 OK (Worker healed!)
    deactivate B
    Retry-->>A: WorkResponse(status="completed")
    deactivate Retry
    
    A->>CB: record_success()
    A-->>Client: HTTP 200 OK (Transparent recovery to client!)
    deactivate A
```

* The client **never sees the error**. Availability is preserved seamlessly.

---

### Scenario 3: Sustained Outage (Breaker Trips $\rightarrow$ Fast Fallback)

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant A as Service A (Coordinator)
    participant CB as Circuit Breaker (State: OPEN)
    participant B as Service B (Down / Unresponsive)

    Note over CB: 5 consecutive failures reached.<br/>Circuit is OPEN!

    Client->>A: POST /trigger (Request #6)
    activate A
    A->>CB: can_execute()?
    CB-->>A: False (Reject: in cooldown)
    
    Note over A,B: ZERO network packets sent to Service B!
    Note over A: Generate fallback response in under 1ms
    
    A-->>Client: HTTP 503 / Degraded Fallback (Total RTT: 2.1ms)
    deactivate A
```

* **Acceptance Criteria Verified:** Service A responds in $<5\text{ms}$ with zero network load sent to Service B.

---

### Scenario 4: Self-Healing Recovery (HALF-OPEN Probe)

```mermaid
sequenceDiagram
    autonumber
    actor Client
    participant A as Service A (Coordinator)
    participant CB as Circuit Breaker
    participant B as Service B (Rebooted & Healthy)

    Note over CB: Cooldown timer (5.0s) expires.
    
    Client->>A: POST /trigger (Incoming Canary)
    activate A
    A->>CB: can_execute()?
    Note over CB: State transition: OPEN -> HALF-OPEN<br/>Permits exactly 1 probe request
    CB-->>A: True (Probe Allowed)
    
    A->>B: Probe Attempt: POST /work
    activate B
    B-->>A: HTTP 200 OK
    deactivate B
    
    A->>CB: record_success()
    Note over CB: State transition: HALF-OPEN -> CLOSED<br/>Failure counter reset to 0
    
    A-->>Client: HTTP 200 OK (System fully self-healed!)
    deactivate A
```

* Normal full-speed operations automatically resume without human intervention.

---

## 4. Code Structure for Milestone 2

To maintain clean separation of concerns, we will structure Service A as follows:

```text
services/service-a/app/
├── __init__.py
├── config.py                 # Timeouts, retry counts, CB thresholds
├── schemas.py                # Request/response validation schemas
├── main.py                   # FastAPI routing and lifespan
└── resilience/
    ├── __init__.py
    ├── circuit_breaker.py    # Thread/async-safe Circuit Breaker state machine
    └── retry.py              # Exponential backoff with Full Jitter implementation
```

---

## 5. Summary Cheatsheet for System Design

| Concern | Pattern | Key Metric to Watch |
| :--- | :--- | :--- |
| **Hanging connections** | Strict Timeouts | Downstream $p99$ response time |
| **Transient blips** | Retry with Jitter | Retry rate vs total request rate ($<5\%$) |
| **Cascading outages** | Circuit Breaker | Breaker state transitions (`CLOSED` $\rightarrow$ `OPEN`) |
| **Recovery time** | Half-Open Probe | Recovery Time Objective (RTO in seconds) |

---

*This concludes the Milestone 2 learning documents. We are ready to implement the resilience engine!*
