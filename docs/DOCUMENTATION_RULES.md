# Technical Documentation Standards & Rules

To ensure all documentation in this project remains accessible, visually consistent, easy to read, and immune to dark/light theme rendering bugs, all contributors and AI agents must adhere to the following rules.

---

## 🚫 What MUST BE AVOIDED (Anti-Patterns)

### 1. NEVER Hardcode Light Background Fills in Diagrams
* **The Mistake:** Using inline styles like `style Node fill:#fee2e2` (light red) or `style Node fill:#fef3c7` (light yellow).
* **Why it breaks:** Most modern code editors (VS Code, Cursor, Obsidian, GitHub Dark Theme) render diagram text as **white or off-white** in dark mode. Placing white text on top of a light pastel background drops the contrast ratio below 1.2:1, making the text **completely invisible / unreadable**.
* **The Rule:** **Do not set `fill` colors on nodes.** Instead, use border coloring (`stroke`) and `stroke-width`:
  ```mermaid
  %% ❌ WRONG (Unreadable in dark mode):
  %% style FastNode fill:#dcfce7,stroke:#16a34a

  %% ✅ CORRECT (High-contrast in BOTH Light & Dark modes):
  %% style FastNode stroke:#16a34a,stroke-width:2px
  ```

---

### 2. NEVER Use `rect rgb(...)` Shading in Sequence Diagrams
* **The Mistake:** Wrapping sequence steps in `rect rgb(254, 243, 199)` to visually group them.
* **Why it breaks:** In dark mode, `rect rgb(...)` forces a bright solid rectangle behind lifelines, while the sequence text, lifeline dashes, and arrows remain white/gray. This causes severe eye-strain and renders lifeline text illegible.
* **The Rule:** Use standard, theme-adapting `Note over ParticipantA,ParticipantB: Step Description` to delineate phases.

---

### 3. NEVER Apply `fill` Styling to Subgraphs
* **The Mistake:** `style SubgraphName fill:#dcfce7`.
* **Why it breaks:** Subgraph fills wash out the background for all child elements within the subgraph, causing all nested labels to lose contrast in dark mode.
* **The Rule:** If you must style a subgraph container, only style its border: `style SubgraphName stroke:#16a34a,stroke-width:2px`.

---

### 4. NEVER Use Unescaped Angle Brackets in Mermaid Text
* **The Mistake:** Writing `<5ms` or `>2s` or `&lt;1ms` directly inside unquoted node text (e.g. `Step["Latency < 5ms"]` or `ServiceB-->>ServiceA: RST (&lt;1ms)`).
* **Why it breaks:** Mermaid's parser will interpret `<` or `>` as HTML tags or parser delimiters, throwing a syntax parsing exception: `Parse error on line X: ... Expecting ... got 'NEWLINE'`.
* **The Rule:** 
  * Replace mathematical comparisons with plain words: `under 5ms`, `over 2s`, `at least 100ms`.
  * If symbols are strictly required, wrap the entire label inside quotes and parentheses: `["Latency (< 5ms)"]`.

---

### 5. NEVER Duplicate Diagrams (No ASCII + Mermaid Duplication)
* **The Mistake:** Providing an ASCII diagram and immediately repeating the exact same flow with a Mermaid diagram.
* **Why it hurts:** It creates visual clutter, increases document length unnecessarily, and causes drift when one diagram is updated while the other is forgotten.
* **The Rule:** **Mermaid is the single source of truth** for all diagrams (architecture, sequence flows, state machines, and topologies). Use ASCII/text blocks only for directory file trees or raw CLI output.

---

### 6. NEVER Use Color as the Sole Indicator of Meaning (Accessibility / WCAG)
* **The Mistake:** Distinguishing a successful node from a failed node only by color (green vs red).
* **Why it hurts:** Color-blind readers cannot distinguish green from red.
* **The Rule:** Always combine visual styling with **explicit textual labels and distinct shapes**:
  * Success: `[Success: 200 OK]` (Rectangle + Green stroke)
  * Decision: `{"Is Circuit Open?"}` (Rhombus shape)
  * Terminal/State: `(["Client Call"])` (Rounded pill shape)
  * Failure: `[Failure: 502 Bad Gateway]` (Rectangle + Red stroke)

---

### 7. NEVER Leave Code Blocks Untyped
* **The Mistake:** Writing generic triple-backtick blocks ` ``` ` without a language identifier.
* **Why it hurts:** Markdown linters flag it, syntax highlighting fails, and readers cannot tell if a snippet is Python, Shell, JSON, or YAML.
* **The Rule:** Always explicitly declare the language:
  * ```` ```python ```` for Python application code
  * ```` ```bash ```` for terminal commands and curl calls
  * ```` ```json ```` for API payloads and response schemas
  * ```` ```mermaid ```` for diagrams
  * ```` ```yaml ```` for Docker Compose configurations

---

### 8. NEVER Use Vague or Relative Path References
* **The Mistake:** Referencing `"in the main file"` or `"in config"`.
* **Why it hurts:** In a multi-service distributed architecture, readers cannot determine whether you mean `service-a`, `service-b`, or the root workspace.
* **The Rule:** Always provide the full relative repository path: `services/service-a/app/main.py`.

---

## 🎨 Approved Styling Cheatsheet for Mermaid

When highlighting nodes in Mermaid flowcharts, use these theme-neutral **stroke-only** definitions:

| Semantic State | Recommended Styling | Example Code |
| :--- | :--- | :--- |
| **Success / Healthy** | `stroke:#16a34a,stroke-width:2px` | `style SuccessNode stroke:#16a34a,stroke-width:2px` |
| **Error / Critical** | `stroke:#dc2626,stroke-width:2px` | `style ErrorNode stroke:#dc2626,stroke-width:2px` |
| **Warning / Degraded** | `stroke:#d97706,stroke-width:2px` | `style WarningNode stroke:#d97706,stroke-width:2px` |
| **Active / Accent** | `stroke:#4338ca,stroke-width:2px` | `style ActiveNode stroke:#4338ca,stroke-width:2px` |

*Notice that none of these styles touch `fill` or `color`. The background card color and text color will seamlessly adapt to the reader's preferred theme.*

---

## ✅ Pre-Commit Documentation Checklist

Before submitting or committing documentation changes, verify each item:

- [ ] **Contrast Verification:** Does the diagram look crisp in both **Light Mode** and **Dark Mode**?
- [ ] **No Light Fills:** Are there any `fill:#...` or `rect rgb(...)` styles that might cause white text on light backgrounds?
- [ ] **Parser Check:** Does every ```` ```mermaid ```` block parse cleanly without syntax errors?
- [ ] **No ASCII Duplicates:** Are there any redundant ASCII diagrams that duplicate a Mermaid diagram?
- [ ] **Language Specifiers:** Does every code block have an explicit language tag (`python`, `bash`, `mermaid`, etc.)?
- [ ] **Exact Paths:** Are all file paths fully qualified from repository root?
