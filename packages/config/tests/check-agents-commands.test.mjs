import { describe, expect, it } from "vitest";
import {
  parseAgentsCommandsSection,
  diffRootTasks,
} from "../../../scripts/check-agents-commands.mjs";

const HEADER = `## 4. Commands\n\n### Root (pnpm workspace + Turborepo)\n\n`;

function table(rows) {
  return (
    "| Task | Command |\n|---|---|\n" +
    rows.map((r) => `| ${r.label} | \`${r.cmd}\` |`).join("\n") +
    "\n"
  );
}

const NEXT_SECTION = "\n## 5. Next section\n\n| Task | Command |\n|---|---|\n";

describe("parseAgentsCommandsSection", () => {
  it("extracts every documented pnpm <task> as a root task", () => {
    const md =
      HEADER +
      table([
        { label: "Install", cmd: "pnpm install --frozen-lockfile" },
        { label: "Lint everything", cmd: "pnpm lint" },
        { label: "Bundle-size check", cmd: "pnpm size" },
      ]) +
      NEXT_SECTION;
    const { rootTasks } = parseAgentsCommandsSection(md);
    expect(rootTasks).toContain("lint");
    expect(rootTasks).toContain("size");
  });

  it("records filtered commands separately from root tasks", () => {
    const md =
      HEADER +
      table([{ label: "Web dev", cmd: "pnpm --filter @candleviewer/web dev" }]) +
      NEXT_SECTION;
    const { rootTasks, filteredCommands } = parseAgentsCommandsSection(md);
    expect(rootTasks).toEqual([]);
    expect(filteredCommands).toEqual(["pnpm --filter @candleviewer/web dev"]);
  });

  it("counts a malformed row (no backtick command) without throwing", () => {
    const md = HEADER + "| Task | Command |\n|---|---|\n| Broken row | no backticks here |\n" + NEXT_SECTION;
    const { malformedRows } = parseAgentsCommandsSection(md);
    expect(malformedRows).toBe(1);
  });

  it("throws if AGENTS.md has no '## 4.' section", () => {
    expect(() => parseAgentsCommandsSection("# Title\n\nNo section here.\n")).toThrow();
  });
});

describe("diffRootTasks", () => {
  it("reports a documented-but-missing task", () => {
    const { missing, undocumented } = diffRootTasks({
      documentedRootTasks: ["lint", "size"],
      turboTasks: ["lint"],
      rootScripts: ["lint"],
    });
    expect(missing).toEqual(["size"]);
    expect(undocumented).toEqual([]);
  });

  it("reports an undocumented extra task", () => {
    const { missing, undocumented } = diffRootTasks({
      documentedRootTasks: ["lint"],
      turboTasks: ["lint", "secretTask"],
      rootScripts: ["lint"],
    });
    expect(missing).toEqual([]);
    expect(undocumented).toEqual(["secretTask"]);
  });

  it("reports nothing when documented tasks exactly match the task graph", () => {
    const { missing, undocumented } = diffRootTasks({
      documentedRootTasks: ["lint", "build"],
      turboTasks: ["lint", "build"],
      rootScripts: ["lint", "build"],
    });
    expect(missing).toEqual([]);
    expect(undocumented).toEqual([]);
  });
});
