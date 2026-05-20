# polilabs Web — Design System & Standards

Read this before building or modifying anything in `web/`. Companion to
`frontend_design.md` (the *implementation plan*); this doc governs *how it
should look, feel, and stay secure*.

## What we are designing

polilabs is a **research instrument** for legislative researchers — not a
marketing site, not a consumer chatbot. The UI's job is to make dense legal
text navigable while never adding a hallucination surface. Every design
decision serves two things: reading and credibility.

North star: it should feel like **Linear, Stripe's dashboard, or a well-built
legal-research terminal** — quiet, dense, precise, trustworthy. A researcher
should trust it on sight.

## The anti-AI-slop rule (non-negotiable)

The fastest way to make this look AI-generated — and therefore untrustworthy —
is the generic LLM frontend aesthetic. **Do not ship any of these:**

- Inter or Geist as the primary font (the single biggest "an AI built this" tell)
- Purple/violet or blue-to-pink gradients; gradient buttons; gradient text
- A hero section, marketing copy, or a landing page — the app opens straight
  into the tool
- Big rounded chat bubbles, an AI avatar/mascot, emoji in UI chrome
- `rounded-2xl` on everything, heavy drop shadows, glassmorphism / backdrop blur
- Everything centered with airy padding — this is a dense tool, not a pitch deck
- The default shadcn slate theme shipped unchanged
- Decorative icons that carry no information

Test: if a screenshot of the UI could be any AI demo, it is wrong. It must look
like *this specific tool*.

## Foundation: own your design system

Build on **unstyled primitives**, never a pre-styled kit:

- `shadcn/ui` — copy-paste components into `web/src/components/ui/`; you own and
  restyle them. Do not accept its default theme or radii.
- `radix-ui/primitives` — the accessibility/behavior layer underneath (focus,
  keyboard nav, dismissals). Use directly for anything bespoke (panels, tabs).

`frontend_design.md` already pins runtime deps minimal (`react`, `zustand`,
`clsx`, `embla-carousel-react`, `diff`). Keep it that way — every component-kit
dependency is a step toward looking templated and a step of supply-chain risk.

## Typography

Type carries this UI — there is almost no other chrome. Use the **IBM Plex**
family: coherent, professional, distinctly not the default, and it provides
sans + serif + mono in one system.

- **IBM Plex Sans** — all UI: left rail, badges, buttons, labels, agent answer.
- **IBM Plex Serif** — the verbatim bill text in the center Text panel. A serif
  gives the law gravitas and signals "this is the source document, not app
  content." This reinforces the anti-hallucination thesis visually.
- **IBM Plex Mono** — section IDs, citations, bill IDs, the tool trace. Anything
  that is a machine identifier.

Self-host via `@fontsource/*` — no Google Fonts CDN call (privacy, offline,
no layout shift).

Reading rules for the Text panel (it is the heart of the product):

- Line length ~66-80 characters. Never full-bleed text.
- Line-height ~1.6 for body legal text.
- A real type scale (e.g. 12 / 13 / 15 / 18 / 24 px) — pick the steps, use only
  those.
- Section numbers and headings earn hierarchy through weight and size, not color.

## Color

A research tool is **near-monochrome with functional accents only**.

- Neutrals: a slightly warm gray ramp (~6 steps). Warm reads less sterile and
  less "AI" than pure slate. Drives background, surfaces, borders, text.
- One accent, used sparingly, for interactive / active state. Not purple, not
  `blue-600` — a deep considered ink-navy or teal.
- **Highlight color** for synced spans: a soft highlighter-yellow. This is
  deliberate — it mirrors marking up a paper document, the exact mental model of
  a legal researcher. Verify contrast: AA-readable serif text must sit on top.
- Badges (congress, tier, relevance): a small categorical set — muted, legible,
  never neon.
- Color is never decorative. If it does not encode state or category, it is a
  neutral.

## Layout discipline

The three-pane shell (left rail / Text / Decomp) is fixed structure — respect it:

- **Density is a feature.** Researchers want maximum signal on screen.
  Comfortable density, not landing-page air. Tighten default shadcn paddings.
- Each pane scrolls independently; the shell itself never scrolls.
- 1px hairline borders separate panes — not shadows, not gaps.
- The Decomp panel must *read as structured data*: cards, mono IDs, diffs,
  outlines — visually distinct from prose, so a user never mistakes extraction
  for generation.
- The verbatim Text panel must read as *a document*: serif, controlled measure,
  quiet.
- The prompt box is pinned to the bottom of the left rail; its disabled state
  while streaming must be visually obvious.

## Interaction & motion

- Motion is functional only: carousel transitions, highlight fade-in, streaming
  text. ~150-200ms, standard easing. No decorative animation.
- The synced highlight is the signature interaction — make it feel instant and
  precise.
- Full keyboard support (Radix gives most of it): arrow between bills, visible
  focus rings, never `outline: none` without a replacement.
- Honor `prefers-reduced-motion`.

## Security — design it secure from the start

- **Rendering bill text:** render bill text and highlight spans only as React
  children / text nodes — never inject raw HTML strings into the DOM. The synced
  highlight wraps substrings by *building* `<mark>` / `<span>` React elements,
  not by assembling markup strings. (XSS via corpus text is low-likelihood, but
  the cost of this rule is zero.)
- **Secrets stay server-side.** Vite inlines every `VITE_`-prefixed env var into
  the *client bundle*. The Anthropic API key must never be `VITE_`-prefixed and
  must never appear anywhere under `web/`. It lives only in `server.py`'s
  environment.
- **No secrets in the bundle**, period — audit `web/dist` before any deploy.
- **CORS:** the dev proxy is permissive; production `allow_origins` must be the
  single deployed origin (already flagged in `frontend_design.md`).
- **REST endpoints are read-only by contract** — keep them that way; validate
  and encode query params (section IDs contain `::`).
- Run `npm audit` and the `semgrep` plugin before merging frontend work. Keep
  runtime deps minimal — fewer deps, smaller supply-chain surface.

## Reference repos — study, do not copy wholesale

- `shadcn-ui/ui` — primitives to copy into the repo and restyle.
- `radix-ui/primitives` — behavior / accessibility layer.
- `alexpate/awesome-design-systems` — study Linear, Stripe, GitHub Primer for
  how serious tools handle density and restraint.
- `birobirobiro/awesome-shadcn-ui` — vetted blocks and themes.
- `OWASP/CheatSheetSeries` — the security reference (XSS, CORS, headers).

## Before you call frontend work done

- Take a screenshot (use the `playwright` plugin) and actually look at it. If it
  reads as a generic AI demo, it is not done.
- Walk the anti-AI-slop list above, item by item.
- Verify: no horizontal overflow; panes scroll independently; focus rings
  visible; AA contrast on the highlight color; no `VITE_`-prefixed secret; bill
  text rendered as React nodes, never injected HTML.
