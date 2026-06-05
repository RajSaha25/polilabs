# Polilabs → IDE for policy researchers — roadmap

Captured from a planning session (2026-06-05). The premise: policy
researchers don't code, but the *shape* of an IDE — multiple panes, in-line
annotation, an agent that points you at exact spans, a shared workspace —
is the right shell for reading and reasoning over legislation. This doc
splits the vision into what shipped, what's safe to build next, and the
forks that need a decision before building.

---

## Shipped this pass (Tier 1 — additive, verified)

- **In-bill annotations.** Select any passage in the Text panel → "Add note"
  pill → inline composer (note text + highlight colour). The block gets a
  persisted highlight + margin flag; a new **Notes** lens in the Decomp panel
  lists every note (verbatim quote + your text), click-to-jump, edit/delete in
  place. Per-user, stored on `auth.db` (`annotations` table), gated behind the
  existing JWT auth. Cross-user isolation + auth gating verified.
  - Data model carries a `source` field (`user` | `agent`) so agent-flagged
    spans render through the same machinery — the create route forces
    `source="user"` so a client can't forge an agent flag.
- **Clearer section delineation** in the Text panel (a hairline rule between
  top-level sections), directly answering "clear lines that delineate section
  from section." Reversible (one CSS block).

Rendering note: with a real nested bill (118-hr-10262, 6 sections / 67
subsections) the Text panel renders cleanly and readably — the
"lines all over the place" complaint did **not** reproduce. To fix the real
issue, point me at the specific bill(s) where it looks broken; it's likely
tied to tables, malformed markers, or unusual nesting in particular bills.

---

## Tier 2 — needs a decision before building

### 1. Section-click → contextual summary  ⚠️ conflicts with a logged decision

You asked: clicking a section summarizes it *in context with the rest of the
bill*. That is an **LLM paraphrase of the law**, which directly contradicts the
project's logged anti-hallucination thesis (Decomp = mechanically-extracted
graph data, *no* LLM paraphrase; readability comes from layout, not rewriting).

I did **not** silently reverse that. Options:

- **A. Keep the guard, add a clearly-fenced AI summary.** A separate, visually
  distinct "AI reading" affordance (not in the verbatim Decomp), labelled as
  model-generated, that always shows the verbatim span alongside and cites the
  exact subsections it's summarizing. Preserves the thesis by *separation*.
- **B. Mechanical "section in context" with no paraphrase.** On click, show the
  section's role structurally: its parent chain, what it defines/amends, what
  cites it — all graph data, zero generation. Honest to the thesis; less
  "summary," more "situate."
- **C. Relax the thesis.** Treat summaries as a first-class feature. Cheapest to
  build, highest hallucination-risk for a product whose pitch is anti-hallucination.

**Recommendation:** A or B (probably A as an opt-in, B always-on). **Your call —
this changes the product's core claim.**

### 2. Decomp: keep, make dynamic, or replace with split-screen

You were torn between (i) keeping decomp as a *better visual guide*,
(ii) making it **agent-driven** (researcher states intent → agent locates the
relevant spans), and (iii) dropping it for an **IDE split-screen** (two bills
side by side, multiple tabs).

These aren't mutually exclusive. The IDE framing suggests: **tabs + split panes
as the shell**, with decomp as *one* openable pane (a structural minimap), not
the fixed right half. Agent-driven location (ii) is the same plumbing as
agent-flagged highlights (#3) and fits the thesis (it points at verbatim spans,
doesn't rewrite). **Decision: do we invest in a tab/split-pane workspace shell?**
That's the biggest UX change and reframes everything else.

### 3. Agent-driven highlighting (agent points you at spans)

Lowest-risk high-value item. The agent, when answering, emits the section ids it
relied on; the frontend flags those spans in the open bill (the `source="agent"`
path already renders). Needs: a small server-side write path for agent flags +
the chat loop to surface "sections to look at." Fits the thesis. **No decision
needed — green-light and I build it.** (Held back this pass only because it
touches the chat/agent loop, which I wanted to plan with you.)

### 4. Collaboration / projects (the deferred epic)

Login → create project → invite ≤5 → shared workspace; each member works in
their own instance, everything ingests into one project session; rotate to see
others' work; query an agent to cross-check the team's findings; supervisor
oversight. Builds on the auth DB and the annotations table just added.

Schema sketch: `projects`, `project_members(role)`, annotations gain a nullable
`project_id` (private when null, shared when set), a per-project activity feed.
Open design question (logged earlier, still open): **how does the shared "memory"
feed the agent — injected into the system prompt each turn, or exposed as a
tool?** Pre-decided: keep the 4-stat box, keep the History-list model.
**Decision: is this the next epic, or does BYO-agent (#6) jump the queue?**

### 5. Data security (hardening pass)

Concrete, mostly non-controversial. Current gaps to close:
- `CORSMiddleware` is `allow_origins=["*"]` (marked DEV-ONLY in code) — lock to
  the real frontend origin(s) for prod.
- Confirm JWT secret is provisioned via env in prod (not the auto-generated
  key file), token TTL, and refresh story.
- Rate-limit `/auth/*` (brute-force) in addition to the existing per-account
  `/chat` token cap.
- The Text panel renders backend-escaped statute HTML via React's raw-HTML
  escape hatch — keep that trust boundary documented; never route agent- or
  user-supplied text through it (user note bodies render as plain text today).
- Per-project access checks once #4 lands (every `/api/*` row scoped to a
  member). Run a Semgrep pass before deploy.
**No deep decision — approve and I work the checklist.**

### 6. Bring-your-own-agent  ★ likely the biggest differentiator

Policy orgs often allow only approved AI tools (e.g. enterprise ChatGPT). The
insight: polilabs is the **MCP harness** — we don't have to supply the model.
`mcp_server.py` already exposes all 12 primitives over MCP stdio. Let a
researcher point *their* approved agent at the polilabs shell.

Paths (not exclusive):
- **Hosted MCP endpoint** (HTTP/SSE transport, not just stdio) so a remote agent
  can connect with a token. Most aligned with "their agent operates in our shell."
- **OpenAI custom-GPT / Actions** against a documented REST surface (we already
  have `/api/*`) — meets ChatGPT users where they are, no MCP client needed.
- **Connector instructions** for Claude Desktop / IDE MCP clients (stdio works
  today; document it).

Decisions: which client(s) first (ChatGPT Actions vs hosted MCP), and the
auth/tenancy model for an external agent (scoped token, per-project, rate-limited).
**This is plausibly where the most strategic value is — worth ranking #1.**

---

## Suggested sequence (my recommendation)

1. **Agent-driven highlighting (#3)** — small, in-thesis, immediate IDE feel.
2. **Security checklist (#5)** — cheap, unblocks any real deployment.
3. **BYO-agent (#6)** — highest strategic value; start with documented REST +
   ChatGPT Actions, then hosted MCP.
4. **Collaboration epic (#4)** — the big one; needs the memory-feed decision.
5. **Section-summary (#1)** and **workspace-shell/decomp (#2)** — after you
   resolve the two product-direction forks above.

Tell me which forks to lock and I'll keep going.
