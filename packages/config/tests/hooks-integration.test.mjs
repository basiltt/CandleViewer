import { describe, expect, it, beforeAll, afterAll } from "vitest";
import { execFileSync } from "node:child_process";
import {
  mkdtempSync,
  rmSync,
  mkdirSync,
  writeFileSync,
  cpSync,
  chmodSync,
  symlinkSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

// Integration test (E02-T07 Test plan §3): exercises the commit-msg,
// pre-commit and pre-push hooks end to end inside a disposable temp git
// repo, using the real .husky/* scripts, commitlint.config.cjs and
// scripts/check-branch-name.mjs copied from the monorepo root. Node
// resolution for commitlint/lint-staged/husky is provided by symlinking the
// temp repo's node_modules back to the real workspace root so the hooks can
// `npx --no-install` the real binaries without a second install.

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(__dirname, "../../..");

function git(cwd, args, opts = {}) {
  return execFileSync("git", args, { cwd, encoding: "utf8", ...opts });
}

describe("commit hooks (temp-repo integration)", () => {
  let dir;

  beforeAll(() => {
    dir = mkdtempSync(path.join(tmpdir(), "cv-hooks-"));
    git(dir, ["init", "-q"]);
    git(dir, ["config", "user.email", "test@example.com"]);
    git(dir, ["config", "user.name", "Test"]);
    git(dir, ["config", "commit.gpgsign", "false"]);

    // Reuse the real node_modules so `npx --no-install` finds the real
    // commitlint/lint-staged binaries without a second `pnpm install`.
    try {
      symlinkSync(path.join(REPO_ROOT, "node_modules"), path.join(dir, "node_modules"), "junction");
    } catch {
      cpSync(path.join(REPO_ROOT, "node_modules", ".bin"), path.join(dir, "node_modules", ".bin"), {
        recursive: true,
      });
    }

    cpSync(path.join(REPO_ROOT, "commitlint.config.cjs"), path.join(dir, "commitlint.config.cjs"));
    mkdirSync(path.join(dir, "scripts"), { recursive: true });
    cpSync(
      path.join(REPO_ROOT, "scripts", "check-branch-name.mjs"),
      path.join(dir, "scripts", "check-branch-name.mjs"),
    );

    mkdirSync(path.join(dir, ".husky"), { recursive: true });
    for (const hook of ["commit-msg", "pre-commit", "pre-push"]) {
      const dest = path.join(dir, ".husky", hook);
      cpSync(path.join(REPO_ROOT, ".husky", hook), dest);
      chmodSync(dest, 0o755);
    }

    writeFileSync(
      path.join(dir, "package.json"),
      JSON.stringify(
        {
          name: "hooks-fixture",
          private: true,
          "lint-staged": { "*.md": ["prettier --write"] },
        },
        null,
        2,
      ),
    );
    git(dir, ["config", "core.hooksPath", ".husky"]);

    writeFileSync(path.join(dir, "README.md"), "# fixture\n");
    writeFileSync(path.join(dir, ".gitignore"), "node_modules/\n");
    git(dir, [
      "add",
      "commitlint.config.cjs",
      "scripts",
      ".husky",
      "package.json",
      "README.md",
      ".gitignore",
    ]);
  });

  afterAll(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("commit-msg rejects a non-conventional message", () => {
    expect(() => git(dir, ["commit", "-m", "fixed stuff"], { stdio: "pipe" })).toThrow();
  });

  it("commit-msg accepts a conventional message with an allowed scope", () => {
    const out = git(dir, ["commit", "-m", "feat(chart-engine): add SDF glyph atlas"]);
    expect(out).toBeTruthy();
    const log = git(dir, ["log", "-1", "--pretty=%s"]).trim();
    expect(log).toBe("feat(chart-engine): add SDF glyph atlas");
  });

  it("pre-push hook script rejects a non-conforming branch name", () => {
    git(dir, ["checkout", "-b", "my-work"]);
    let stderr = "";
    expect(() => {
      try {
        execFileSync("node", ["scripts/check-branch-name.mjs", "my-work"], {
          cwd: dir,
          stdio: "pipe",
        });
      } catch (err) {
        stderr = String(err.stderr);
        throw err;
      }
    }).toThrow();
    expect(stderr).toMatch(/branch-naming pattern/);
  });

  it("check-branch-name accepts a conforming branch name", () => {
    expect(() =>
      execFileSync("node", ["scripts/check-branch-name.mjs", "feat/of-1-demo"], {
        cwd: dir,
        stdio: "pipe",
      }),
    ).not.toThrow();
  });
});
