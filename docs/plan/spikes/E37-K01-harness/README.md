# E37-K01 throwaway harness (not production code)

Pinned: react 18, @xyflow/react 12.12.0, elkjs 0.12.0, @dagrejs/dagre 3.1.1, vite 5, playwright-core.
Run in an empty dir: `npm i <pins>`, copy these files, `npx vite build`, `DUR=10000 node bench.mjs`, `node layout.mjs`.
`gen.mjs` builds an IR-shaped graph (trigger -> compare/temporal -> bool -> action), deterministic seed.
