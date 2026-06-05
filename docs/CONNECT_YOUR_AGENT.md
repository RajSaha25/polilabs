# Connect your own agent to polilabs

Many policy teams can only use an **approved** AI tool (e.g. enterprise
ChatGPT). polilabs doesn't need to supply the model — it supplies the
*tools*. Point your approved agent at the polilabs tool surface and it
operates inside the polilabs shell: searching the corpus, pulling verbatim
sections, walking citations — all the primitives the built-in agent uses.

The tools are **read-only and corpus-scoped**, and they return
mechanically-extracted, **verbatim** data — never a paraphrase. That's the
point: your agent quotes the law, it doesn't trust a summary of it.

## 1. Mint a connector token

While signed in to polilabs, create a token for your agent:

```
POST /auth/connector-token
Authorization: Bearer <your session token>
Content-Type: application/json

{ "label": "My ChatGPT" }
```

The response contains a long-lived `token` (90 days) shown **once**. Store
it in your agent's connector config. List your tokens at
`GET /auth/connector-tokens`; revoke one at
`DELETE /auth/connector-token/{jti}` (kills it immediately, even though
the JWT is otherwise stateless).

Every tool call sends the token as `Authorization: Bearer <token>`.

## 2a. ChatGPT (custom GPT → Actions)

1. Create a custom GPT → **Configure** → **Actions** → **Add action**.
2. Import the schema from `https://<polilabs-backend>/openapi.json`
   (the `/api/*` operations are described there, with a Bearer security
   scheme already declared).
3. Authentication → **API Key** → **Bearer**, paste the connector token.
4. Tell the GPT, in its instructions, to use the actions to search and
   quote bills verbatim and to never invent statutory text.

`GET /connector` returns a compact, self-describing manifest of the tools
if you'd rather wire them up by hand.

## 2b. MCP clients (Claude Desktop, IDEs) — stdio, available today

`mcp_server.py` exposes the same primitives over MCP stdio. Configure your
MCP client:

```json
{
  "mcpServers": {
    "polilabs": {
      "command": "/path/to/polilabs/.venv/bin/python",
      "args": ["/path/to/polilabs/mcp_server.py"],
      "env": {
        "POLILABS_DB":   "/path/to/polilabs/data/polilabs.db",
        "POLILABS_KUZU": "/path/to/polilabs/data/polilabs.kuzu"
      }
    }
  }
}
```

This path runs against a local corpus copy and needs no token (it's a
local process you own).

## 2c. Hosted MCP over HTTP — next step (not yet built)

For a remote MCP client to connect to the hosted backend (rather than
running `mcp_server.py` locally), polilabs needs an MCP-over-HTTP/SSE
endpoint with connector-token auth. The token plumbing above is the
foundation; the HTTP transport is the remaining piece. Tracked in
`docs/IDE_ROADMAP.md` (#6).

## The tools

| Tool | Endpoint |
|------|----------|
| Search corpus | `GET /api/search?query=…&topic=…` |
| Bill + ToC | `GET /api/bill/{bill_id}` |
| Full section tree | `GET /api/bill/{bill_id}/sections` |
| Defined terms | `GET /api/bill/{bill_id}/defined_terms` |
| Amendments | `GET /api/bill/{bill_id}/amendments` |
| Section verbatim text | `GET /api/section?section_id=…` |
| Citation graph | `GET /api/citation_graph?section_id=…` |
| Resolve a citation | `GET /api/resolve?citation_string=…` |
| Corpus coverage | `GET /api/coverage` |

All require the `Authorization: Bearer <connector token>` header.
