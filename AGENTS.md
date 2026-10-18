# Repository Instructions & Agent Guidelines

Welcome to the **Zero-Logic Microservices Architecture Sandbox** repository.
All AI assistants, contributors, and subagents working in this codebase must adhere to the following architectural, coding, and documentation standards.

---

## 1. Documentation & Diagrams
* **Documentation & Diagram Standards:** When creating or modifying documentation or Mermaid diagrams, **read `docs/DOCUMENTATION_RULES.md` first** and strictly follow its syntax, dark/light mode contrast, and formatting rules. Only read that file when you are actively authoring or modifying documentation/diagrams to save context tokens.

---

## 2. Python & Architecture Standards

* **Package Manager:** `uv` workspace (`pyproject.toml` + `uv.lock`). Run `uv sync` to manage dependencies; do not use raw `pip install`.
* **Services:** FastAPI with async-first design (`async def`, non-blocking I/O).
* **HTTP Client:** `httpx.AsyncClient` with connection pooling. Never use blocking `requests` inside async endpoints.
* **Linter & Formatter:** `uv run ruff check --fix .` must pass with zero errors.
* **Testing:** `uv run pytest tests/` must always pass before committing.
* **Docker:** Containers run with lightweight Alpine/Slim images using `uv sync --frozen --no-install-project`.
