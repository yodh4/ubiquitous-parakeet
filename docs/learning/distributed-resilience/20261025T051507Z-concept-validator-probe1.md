---
schema_version: 1
record_id: "20261025T051507Z-concept-validator-probe1"
artifact_type: concept-assessment
concept_id: distributed-resilience
scope: "Distributed resilience patterns: timeouts, retries, circuit breakers, and pattern composition"
learning_objective: "Explain the mechanisms, failure modes, state transitions, and composition rules of strict timeouts, retries with backoff/jitter, and circuit breakers."
project_ref: "."
environment_ref: null
source_revision: "d485a56acadf4af5a5b6d6d7161f747eb13d9c9a"
source_paths:
  - "docs/milestone-2/00-distributed-failure-mechanics.md"
  - "docs/milestone-2/01-strict-timeouts.md"
  - "docs/milestone-2/02-retries-backoff-jitter.md"
  - "docs/milestone-2/03-circuit-breaker.md"
  - "docs/milestone-2/04-pattern-composition.md"
working_tree: "dirty: .gitignore, AGENTS.md modified"
created_at: "2026-10-25T05:15:07Z"
updated_at: "2026-10-25T05:43:13Z"
source_harness: pi
session_ref: null
status: awaiting-learner
assistance: guided
evidence_kind: [learner-answer]
related_records: []
---

# Concept Assessment: Milestone 2 Distributed Resilience Mechanisms

## Competencies Assessed
1. **Socket Mechanics & Timeout Discrimination**: Distinguishing network phases (connect vs read) and understanding socket resource consumption under failure.
2. **Resilience Pattern Nesting & Failure Accounting**: Explaining how Circuit Breaker and Retry interact regarding failure counting, retry budgets, and request lifecycle.
3. **Circuit Breaker State Machine & Recovery**: Describing state transitions (`CLOSED` -> `OPEN` -> `HALF-OPEN` -> `CLOSED`/`OPEN`) and concurrency handling during probe evaluation.

## Prompt
Consider Service A calling downstream Service B over HTTP. Service A configures:
- A strict per-attempt socket timeout: `connect = 500ms`, `read = 1000ms`.
- A retry policy: maximum 3 attempts with exponential backoff + jitter.
- A circuit breaker wrapping the call: failure threshold of 5 consecutive failures, cooldown of 5.0 seconds.

Please answer the following three conceptual questions based on your understanding of the mechanisms:

1. **Timeout Discrimination & Resource Retention**:
   - Scenario A: Service B's host is completely powered off (or dropped silently by a router without sending a TCP RST packet).
   - Scenario B: Service B successfully completes the TCP handshake, but hangs during a stop-the-world Garbage Collection pause before sending any response bytes.
   Which specific timeout timer fires in Scenario A vs Scenario B? In both scenarios, what happens to Service A's connection and socket resources while the timer is running?

2. **Pattern Composition & Failure Accounting**:
   - When Service B experiences an outage (every HTTP call times out), Service A processes incoming client requests. In the standard "Onion" composition model (Circuit Breaker outer, Retry middle, Timeout inner), does one client request that exhausts all 3 retry attempts count as **1 failure** or **3 failures** against the Circuit Breaker's threshold of 5? Why?
   - Once the Circuit Breaker trips to `OPEN`, what happens to the very next incoming request in terms of network I/O, retry loop execution, and response time?

3. **Circuit Breaker State Transitions & Recovery**:
   - When the 5-second cooldown timer expires and the Circuit Breaker enters `HALF-OPEN`, how does it handle new incoming traffic if multiple concurrent requests arrive at the same millisecond?
   - What exact criterion triggers the transition from `HALF-OPEN` back to `CLOSED` versus re-tripping back to `OPEN`?

## Initial Learner Answer
> "damn i dont know the answer for all of it. it seems like i havent really understand the concept after all, i just know what x is, what y is, but when it comes to scenario based question, i cant answer any of it."

## Assistance Timeline
- `2026-10-25T05:15:07Z`: Prompt presented with `assistance: none`. Awaiting initial independent response.
- `2026-10-25T05:34:00Z`: Learner reported difficulty bridging theoretical definitions to runtime/scenario mechanics.
- `2026-10-25T05:35:06Z`: Learner requested starting with easier, more straightforward questions. Switched assistance to `guided` scaffolding mode, starting with core timeout mechanics.
- `2026-10-25T05:43:13Z`: Scaffolding probe on `connect_timeout` vs `read_timeout`. Learner answered:
  1. Power off / never picked up -> `connect_timeout` (Correct)
  2. Answered but silent during calculation -> `read_timeout` (Correct)

## Misconceptions Identified
*no observation yet*

## Feedback & Analysis
*no observation yet*

## Competency Scores
- **Socket Mechanics & Timeout Discrimination**: `not-assessed`
- **Resilience Pattern Nesting & Failure Accounting**: `not-assessed`
- **Circuit Breaker State Machine & Recovery**: `not-assessed`

## Areas for Revision / Gaps
*no observation yet*
