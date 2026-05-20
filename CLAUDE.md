## Frontend design

The web UI lives in `web/` (React + Vite + TypeScript + Tailwind).

Rules:
- Before building or modifying anything in `web/`, read `web/DESIGN.md` — the design system, anti-AI-slop standards, and frontend security rules for the polilabs research UI.
- `frontend_design.md` is the implementation plan; `web/DESIGN.md` governs visual language and security.

## graphify

This project has a graphify knowledge graph at graphify-out/.

Rules:
- Before answering architecture or codebase questions, read graphify-out/GRAPH_REPORT.md for god nodes and community structure
- If graphify-out/wiki/index.md exists, navigate it instead of reading raw files
- After modifying code files in this session, run `graphify update .` to keep the graph current (AST-only, no API cost)
