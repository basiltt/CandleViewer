#!/usr/bin/env node
// scripts/check-agents-commands.mjs
//
// E02-T01: parses the `|`-delimited command tables in `AGENTS.md` §4 and
// verifies every root-level `pnpm <task>` command named there resolves to a
// real Turborepo pipeline task (turbo.json) or root package.json script, and
// that every root-level task defined in turbo.json/package.json is
// documented somewhere in AGENTS.md §4. Exits non-zero naming the mismatch.
//
// Filtered commands (`pnpm --filter <pkg> <task>`) are recorded but not
// treated as fatal when the target package does not exist yet (most
// workspace packages land in later tickets) — see docs/plan/backlog E02-T01
// "Out of scope".

import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import path from "node:path";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "..");

/**
 * Extract every backtick-quoted `pnpm ...` command from the AGENTS.md §4
 * section's markdown tables.
 * @param {string} agentsMdText
 * @returns {{ rootTasks: string[], filteredCommands: string[], malformedRows: number }}
 */
export function parseAgentsCommandsSection(agentsMdText) {
  const lines = agentsMdText.split(/\r?\n/);
  const sectionStart = lines.findIndex((l) => /^##\s+4\./.test(l));
  if (sectionStart === -1) {
    throw new Error("AGENTS.md has no '## 4.' commands section");
  }
  // This ticket (E02-T01) scaffolds only the root pnpm/Turborepo task graph.
  // Scope the parse to the "### Root (pnpm workspace + Turborepo)" subsection
  // so commands owned by later epics (e2e, chaos, a11y, k6, gitleaks, ...)
  // aren't flagged as missing before their scaffolding tickets land.
  const rootHeadingStart = lines.findIndex(
    (l, i) => i > sectionStart && /^###\s+Root\s+\(pnpm workspace/.test(l),
  );
  const scanStart = rootHeadingStart === -1 ? sectionStart : rootHeadingStart;
  let sectionEnd = lines.findIndex(
    (l, i) => i > scanStart && /^(##|###)\s/.test(l),
  );
  if (sectionEnd === -1) sectionEnd = lines.length;
  const section = lines.slice(scanStart, sectionEnd);

  const rootTasks = new Set();
  const filteredCommands = new Set();
  let malformedRows = 0;

  for (const line of section) {
    const trimmed = line.trim();
    if (!trimmed.startsWith("|")) continue;
    // Skip header/separator rows.
    if (/^\|\s*-+\s*\|/.test(trimmed)) continue;
    if (/^\|\s*Task\s*\|/.test(trimmed)) continue;

    const cells = trimmed
      .split("|")
      .slice(1, -1)
      .map((c) => c.trim());
    if (cells.length < 2) {
      malformedRows += 1;
      continue;
    }

    const commandCell = cells[cells.length - 1];
    const backtickMatches = [...commandCell.matchAll(/`([^`]+)`/g)].map((m) => m[1]);
    if (backtickMatches.length === 0) {
      malformedRows += 1;
      continue;
    }

    for (const raw of backtickMatches) {
      const cmd = raw.trim();
      const rootMatch = cmd.match(/^pnpm\s+([a-z][a-z:-]*)$/);
      const filteredMatch = cmd.match(/^pnpm\s+--filter\s+(\S+)\s+([a-z][a-z:-]*)$/);
      if (rootMatch) {
        rootTasks.add(rootMatch[1]);
      } else if (filteredMatch) {
        filteredCommands.add(cmd);
      }
      // Non-pnpm commands (make, node, alembic, uv, pytest, ruff, ...) are
      // out of scope for this JS task-graph check.
    }
  }

  return {
    rootTasks: [...rootTasks].sort(),
    filteredCommands: [...filteredCommands].sort(),
    malformedRows,
  };
}

/**
 * @param {{ documentedRootTasks: string[], turboTasks: string[], rootScripts: string[] }} args
 */
export function diffRootTasks({ documentedRootTasks, turboTasks, rootScripts }) {
  const resolvable = new Set([...turboTasks, ...rootScripts]);
  const missing = documentedRootTasks.filter((t) => !resolvable.has(t));
  const undocumented = [...resolvable].filter(
    (t) => !documentedRootTasks.includes(t) && t !== "check:agents-commands",
  );
  return { missing: missing.sort(), undocumented: undocumented.sort() };
}

function loadRepoState(repoRoot) {
  const agentsMdText = readFileSync(path.join(repoRoot, "AGENTS.md"), "utf8");
  const turboJson = JSON.parse(readFileSync(path.join(repoRoot, "turbo.json"), "utf8"));
  const rootPackageJson = JSON.parse(
    readFileSync(path.join(repoRoot, "package.json"), "utf8"),
  );
  return { agentsMdText, turboJson, rootPackageJson };
}

export function runCheck(repoRoot) {
  const { agentsMdText, turboJson, rootPackageJson } = loadRepoState(repoRoot);
  const { rootTasks, filteredCommands, malformedRows } =
    parseAgentsCommandsSection(agentsMdText);
  const turboTasks = Object.keys(turboJson.tasks ?? {});
  const rootScripts = Object.keys(rootPackageJson.scripts ?? {});

  const { missing, undocumented } = diffRootTasks({
    documentedRootTasks: rootTasks,
    turboTasks,
    rootScripts,
  });

  return { missing, undocumented, malformedRows, filteredCommands };
}

/* c8 ignore start -- CLI entrypoint, exercised via integration shell test */
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const repoRootArg = process.argv[2] ? path.resolve(process.argv[2]) : REPO_ROOT;
  if (!existsSync(path.join(repoRootArg, "AGENTS.md"))) {
    console.error(`check-agents-commands: no AGENTS.md found under ${repoRootArg}`);
    process.exit(2);
  }
  const { missing, undocumented, malformedRows } = runCheck(repoRootArg);

  if (malformedRows > 0) {
    console.error(
      `check-agents-commands: ${malformedRows} malformed table row(s) in AGENTS.md §4 (no backtick-quoted command found)`,
    );
  }
  if (missing.length > 0) {
    console.error(
      `check-agents-commands: AGENTS.md §4 documents task(s) not present in turbo.json or package.json scripts: ${missing.join(", ")}`,
    );
  }
  if (undocumented.length > 0) {
    console.error(
      `check-agents-commands: turbo.json/package.json define user-facing task(s) not documented in AGENTS.md §4: ${undocumented.join(", ")}`,
    );
  }
  if (missing.length > 0 || undocumented.length > 0) {
    process.exit(1);
  }
  console.log("check-agents-commands: AGENTS.md §4 matches the turbo task graph.");
}
/* c8 ignore stop */
