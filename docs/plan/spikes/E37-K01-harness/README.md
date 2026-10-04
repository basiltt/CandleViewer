# E37-K01 throwaway harness (not production code)

Pinned: react 18, @xyflow/react 12.12.0, elkjs 0.12.0, @dagrejs/dagre 3.1.1, vite 5, playwright-core.
Run in an empty dir: `npm i <pins>`, copy these files, `npx vite build`, `DUR=10000 node bench.mjs`, `node layout.mjs`.
`gen.mjs` builds an IR-shaped graph (trigger -> compare/temporal -> bool -> action), deterministic seed.

Review round 2 additions: `rete.jsx`/`rete.html` (Rete.js 2 DOM prototype, rete@2 + rete-area-plugin@2, same 200-node graph),
`bench2.mjs` (frame-rate-limit/vsync disabled, CPU throttle 1x and 4x via CDP, React Flow vs Rete), `kb.mjs`
(keyboard connect with ArrowUp/Down candidate traversal, roving tabindex, Escape cancel). `gen.js` is a copy of `gen.mjs`
(vite import). Results recorded in `../E37-K01-results.json`.
