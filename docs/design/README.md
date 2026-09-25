# Design tooling — Penpot (owner decision 2026-09-25)

UI/UX tickets (`E*-D*`, screens `SCR-*`, components `CMP-*`) are executed in **Penpot** (open-source,
MPL-2.0) instead of Figma. Agents drive it through the **official Penpot MCP server**, which exposes
`high_level_overview`, `penpot_api_info`, `execute_code` (Penpot Plugin API), `export_shape`, `import_image`.

## Topology

| Piece | Where | Notes |
|---|---|---|
| Penpot instance | https://design.penpot.app (owner's account; team **CandleViewer**) | Cloud-hosted for now. Self-hosting in WSL2 is a later option; nothing on the agent side changes. |
| MCP server | `http://localhost:4401/mcp` (Streamable HTTP) | Built from `C:\Users\basil\Desktop\Projects\PublicProjects\penpot\mcp` (Penpot `develop`, 2.18.0-dev). Registered user-scope in `~/.claude.json` as `penpot`. |
| Plugin server | `http://localhost:4400/manifest.json` | Serves the Penpot MCP plugin into the browser. |
| WS bridge | `ws://localhost:4402` | Plugin ↔ MCP server. |

Start everything: `C:\Users\basil\Desktop\Projects\PublicProjects\penpot\mcp\start-penpot-mcp.cmd`
(or `pnpm run start` in that directory). Log: `%USERPROFILE%\.cache\penpot-mcp.log` when started from Claude.

## Session ritual (human, once per session)

1. Start the servers (above).
2. Open the design file in Penpot in a browser tab (Firefox or Chromium ≥142 — approve the
   "access local network" prompt).
3. Plugins menu → load `http://localhost:4400/manifest.json` → open the plugin → **Connect to MCP server**.
4. Keep that tab and the plugin panel open for the whole agent session (browser tab suspension drops the bridge).

## Rules for design agents

- One Penpot **file per epic**, one **page per screen** (`SCR-nnn <name>`); components live in the shared
  **CandleViewer DS** library file (`packages/ui` tokens are the source of truth — never invent a token).
- Deliverables per design ticket (all three, or the ticket is not Done):
  1. Penpot artefacts (frames named `SCR-nnn/<state>`; every state in `14-screens-catalogue.md`).
  2. `docs/design/<epic>/<ticket>.md` — spec: purpose, states, data, interactions, hotkeys, a11y notes,
     token usage, and **PNG exports** of each frame (`export_shape`) committed under `docs/design/<epic>/img/`.
  3. Storybook stories for any `CMP-*` touched (`packages/ui`).
- Design sign-off = PR merge of the spec + exports; the Penpot file link goes in the ticket comment.
- `execute_code` runs arbitrary JS in the plugin sandbox: only mutate the file named in the ticket; never
  delete pages/components you did not create; export before and after large mutations.
