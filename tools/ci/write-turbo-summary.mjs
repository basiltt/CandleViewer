#!/usr/bin/env node
// E03-T02: emit a per-task cache hit/miss + duration line to the GitHub Actions
// job summary from Turborepo's `--summarize` run file
// (`.turbo/runs/<uuid>.json`), per the ticket's "Observability" note (these
// feed the `ci-metrics` artifact from E03-T01). Picks the most recently
// written summary file, since each `turbo run` invocation writes a new one.
//
// Usage: node tools/ci/write-turbo-summary.mjs <lane-name>

import { readFileSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

const TURBO_RUNS_DIR = path.join(".turbo", "runs");

function findLatestSummary(dir) {
  let files;
  try {
    files = readdirSync(dir).filter((f) => f.endsWith(".json"));
  } catch {
    return null;
  }
  if (files.length === 0) return null;
  const withMtime = files.map((f) => {
    const full = path.join(dir, f);
    return { full, mtime: statSync(full).mtimeMs };
  });
  withMtime.sort((a, b) => b.mtime - a.mtime);
  return withMtime[0].full;
}

export function renderSummary(laneName, summaryJson) {
  const tasks = Array.isArray(summaryJson.tasks) ? summaryJson.tasks : [];
  const lines = [
    `### JS lane: \`${laneName}\``,
    "",
    "| package | task | cache | duration |",
    "|---|---|---|---|",
  ];
  for (const task of tasks) {
    const cache = task.cache && task.cache.status ? task.cache.status : "unknown";
    const durationMs =
      task.execution && typeof task.execution.exitCode === "number" && task.execution.startTime
        ? task.execution.endTime - task.execution.startTime
        : null;
    const duration = durationMs === null ? "n/a" : `${durationMs} ms`;
    lines.push(`| ${task.package ?? "?"} | ${task.task ?? "?"} | ${cache} | ${duration} |`);
  }
  if (tasks.length === 0) {
    lines.push("| _(no task summary available)_ | | | |");
  }
  return lines.join("\n") + "\n";
}

function main() {
  const laneName = process.argv[2] ?? "unknown";
  const summaryPath = findLatestSummary(TURBO_RUNS_DIR);
  if (!summaryPath) {
    process.stdout.write(
      `### JS lane: \`${laneName}\`\n\n_no Turborepo run summary found (\`${TURBO_RUNS_DIR}\`)_\n`,
    );
    return;
  }
  const summaryJson = JSON.parse(readFileSync(summaryPath, "utf8"));
  process.stdout.write(renderSummary(laneName, summaryJson));
}

const isMain = process.argv[1] && process.argv[1].endsWith("write-turbo-summary.mjs");
if (isMain) {
  main();
}
