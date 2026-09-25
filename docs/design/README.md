# Design tooling — Penpot (owner decision 2026-09-25)

UI/UX tickets (`E*-D*`, screens `SCR-*`, components `CMP-*`) are executed in **Penpot** (open-source,
MPL-2.0) instead of Figma. Agents drive it through the **official Penpot MCP server**, which exposes
`high_level_overview`, `penpot_api_info`, `execute_code` (Penpot Plugin API), `export_shape`, `import_image`.

## Topology

| Piece | Where | Notes |
|---|---|---|
| Penpot instance | https://design.penpot.app — team **CandleViewer** (`team-id b564c72c-f31f-81ec-8008-b109a9175d0b`) | Cloud-hosted for now. Self-hosting in WSL2 is a later option; nothing on the agent side changes. |
| MCP server | **Hosted:** `https://design.penpot.app/mcp/stream?userToken=<MCP key>` (Streamable HTTP) | Registered user-scope in `~/.claude.json` as `penpot`. The key is per-user (Your account → Integrations → MCP Server) and lives only in `~/.claude.json` — never in the repo or a ticket. Tools: `high_level_overview`, `penpot_api_info`, `execute_code`, `export_shape` (no `import_image` on hosted). |
| Plugin | Penpot's built-in **MCP plugin** (Plugins menu in any open file) | The plugin *is* the bridge: without an open, connected plugin every tool call fails with "No plugin instance connected". |
| Local fallback | `C:\Users\basil\Desktop\Projects\PublicProjects\penpot\mcp` → `start-penpot-mcp.cmd` (`:4401/mcp`, plugin `:4400/manifest.json`, WS `:4402`) | Built 2026-09-25 from Penpot `develop`. Use if the hosted endpoint is down or when self-hosting. |

## Session ritual (human, once per session)

1. Open the design file in Penpot in a browser tab.
2. Plugins menu → **Penpot MCP** → **Connect**.
3. Keep that tab and the plugin panel open for the whole agent session (browser tab suspension drops the bridge).

## Fonts

Team fonts uploaded 2026-09-25: **Inter** v4.1 and **JetBrains Mono** v2.304, each as 8 static TTFs
(Regular/Medium/SemiBold/Bold + italics = weight tokens 400/500/600/700). JetBrains Mono needed its Macintosh
`name` records stripped (fontTools): opentype.js 2.x `getEnglishName()` reads only the first platform table
present, so Penpot silently skipped the files (upstream bug, to be filed). Fixed set:
`C:\Users\basil\Downloads\CandleViewer-fonts\upload-static\JetBrainsMono-fixed\`.

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
