# Repository Instructions & Agent Guidelines

Welcome to the **Zero-Logic Microservices Architecture Sandbox** repository.
All AI assistants, contributors, and subagents working in this codebase must adhere to the following architectural, coding, and documentation standards.

---

## 1. Documentation & Mermaid Diagram Standards

Whenever writing or editing Markdown documents in `docs/`:

### Rule 1: Always Ensure High Contrast in BOTH Light & Dark Modes
* **Default:** Use border-only styling (`stroke:#<color>, stroke-width:2px`) on nodes so the card background and text automatically inherit the user's theme.
* **Layer/Tier Distinction:** When background fills are needed (e.g., distinguishing layers in an Onion/Multi-tier architecture):
  * **ALWAYS pair saturated dark fills with explicit white text and bright borders**:
    ```mermaid
    style Layer1 fill:#78350f,stroke:#f59e0b,stroke-width:3px,color:#ffffff
    style Layer2 fill:#1e3a8a,stroke:#3b82f6,stroke-width:3px,color:#ffffff
    style Layer3 fill:#4c1d95,stroke:#8b5cf6,stroke-width:3px,color:#ffffff
    ```
  * **NEVER use light pastel fills (`#fee2e2`, `#fef3c7`, `#dcfce7`)** without an explicit dark text color, as they cause invisible white-on-light text in Dark Mode.

### Rule 2: NEVER Use `rect rgb(...)` in Sequence Diagrams
* Shaded rectangles in sequence diagrams break dark mode rendering.
* Use theme-adaptive `Note over ParticipantA,ParticipantB: Step Description` to delineate phases instead.

### Rule 3: NEVER Use Unescaped Angle Brackets in Mermaid Node Labels
* Never write `<5ms` or `>2s` or `&lt;` in unquoted node text (causes parser syntax exceptions).
* Write `under 5ms`, `over 2s`, or wrap in quotes `["Latency (< 5ms)"]`.

### Rule 4: No Duplicate Diagrams
* Mermaid is the single source of truth for diagrams.
* Do not repeat a Mermaid flow with an ASCII art diagram. Use text blocks only for directory trees and raw terminal output.

*See `docs/DOCUMENTATION_RULES.md` for the full checklist and anti-patterns.*

---

## 2. Python & Architecture Standards

* **Package Manager:** `uv` workspace (`pyproject.toml` + `uv.lock`). Run `uv sync` to manage dependencies; do not use raw `pip install`.
* **Services:** FastAPI with async-first design (`async def`, non-blocking I/O).
* **HTTP Client:** `httpx.AsyncClient` with connection pooling. Never use blocking `requests` inside async endpoints.
* **Linter & Formatter:** `uv run ruff check --fix .` must pass with zero errors.
* **Testing:** `uv run pytest tests/` must always pass before committing.
* **Docker:** Containers run with lightweight Alpine/Slim images using `uv sync --frozen --no-install-project`.
