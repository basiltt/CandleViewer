# ADR-0029: Rule node-graph library and layout placement

- Status: Proposed (owner approval pending)
- Date: 2026-10-04
- Ticket: E37-K01; evidence: `docs/plan/spikes/E37-K01.md`

## Context
SCR-082 needs 200 nodes at 60 fps and a keyboard-operable connect flow; CMP-146 requires DOM-rendered nodes for
the a11y mirror.

## Decision
1. Use **@xyflow/react (React Flow) 12.x, pinned exactly**, with fully controlled `nodes`/`edges` owned by
   `packages/rule-graph`. Ports are our own focusable elements; connect is a keyboard state machine in our code.
2. **No node cap** for now; show a soft warning at 200 nodes until E37-Q04 re-measures on reference hardware
   and in Electron. If < 45 fps there, apply the spike's pre-agreed cap (e.g. 120).
3. **Auto-layout runs in a web worker** using **dagre** (@dagrejs/dagre); elkjs only if routing needs justify
   its ~442 KB gz cost. Main-thread layout at 200 nodes measured ~230 ms (> 100 ms limit).
4. `graph_layout` is persisted separately and excluded from the canonical IR hash (ADR-0026).
5. Rete.js is the fallback if E37-S02 finds a keyboard blocker requiring a fork.

## Consequences
Editor route is lazy-loaded (~60 KB gz library delta). Dependency additions need licence/SCA review in E37-T01.
Confidence is bounded by the spike's limitations (headless Chromium, non-reference hardware).
