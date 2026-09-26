import { describe, expect, it } from "vitest";
import lint from "@commitlint/lint";
import loadConfig from "@commitlint/load";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = path.resolve(__dirname, "../../../commitlint.config.cjs");

async function check(message) {
  const { rules, parserPreset } = await loadConfig(
    {},
    { file: CONFIG_PATH, cwd: path.dirname(CONFIG_PATH) },
  );
  return lint(message, rules, { parserOpts: parserPreset?.parserOpts });
}

describe("commitlint.config.cjs", () => {
  const cases = [
    { msg: "feat(chart-engine): add SDF glyph atlas", valid: true },
    { msg: "fix(oms-execution): correct rounding on SL amend", valid: true },
    { msg: "chore(infra): bump turbo to 2.4.0", valid: true },
    { msg: "docs(docs): clarify branch naming", valid: true },
    { msg: "refactor(config): simplify vitest preset", valid: true },
    {
      msg: "feat(chart-engine)!: change public draw API\n\nBREAKING CHANGE: renamed dispose()\n",
      valid: true,
    },
    { msg: "fixed stuff", valid: false },
    { msg: "banana(chart-engine): not a real type", valid: false },
    { msg: "feat: missing scope", valid: false },
    { msg: "feat(not-a-real-scope): unknown scope", valid: false },
    {
      msg: `feat(chart-engine): ${"a".repeat(110)}`,
      valid: false,
    },
    { msg: "feat(chart-engine):missing space after colon", valid: false },
  ];

  for (const { msg, valid } of cases) {
    it(`${valid ? "accepts" : "rejects"}: ${JSON.stringify(msg.split("\n")[0])}`, async () => {
      const result = await check(msg);
      expect(result.valid).toBe(valid);
    });
  }
});
