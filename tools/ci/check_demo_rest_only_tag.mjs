#!/usr/bin/env node
// E03-T06: asserts the `@demo-rest-only` tag still resolves to at least one
// Playwright spec (01-sdlc-and-branching.md §9's "the harness must exist
// before R3 needs it" — the tag disappearing from the suite configuration,
// e.g. a rename or an accidental delete, must fail this job rather than
// `e2e:staging` silently running zero tests and reporting green).
//
// Usage: node tools/ci/check_demo_rest_only_tag.mjs
import { execFileSync } from "node:child_process";

const CONFIG = "apps/web/e2e/playwright.config.ts";
const TAG = "@demo-rest-only";

function main() {
  let output;
  try {
    output = execFileSync("npx", ["playwright", "test", "-c", CONFIG, "--grep", TAG, "--list"], {
      encoding: "utf8",
      cwd: "apps/web",
    });
  } catch (err) {
    console.error(`CI-E2E-002: failed to list Playwright specs for tag ${TAG}`);
    console.error(err.stdout ?? err.message);
    process.exit(1);
  }

  // Playwright's --list output ends with "Total: N test(s) in M file(s)".
  const match = output.match(/Total:\s*(\d+)\s*test/i);
  const total = match ? Number(match[1]) : 0;

  if (total < 1) {
    console.error(
      `CI-E2E-002: the \`${TAG}\` tag matched 0 specs — the demo-REST-only harness ` +
        "must always have at least one spec (see apps/web/e2e/demo-rest-only.spec.ts). " +
        "Either the tag was renamed/removed, or the placeholder spec was deleted.",
    );
    process.exit(1);
  }

  console.log(`\`${TAG}\` harness present: ${total} matching spec(s).`);
}

main();
