// Conventional-commit enforcement (C-4.10, CONSTITUTION.md §9 #20).
// Scopes mirror the `area/*` board labels (docs/plan/01-sdlc-and-branching.md §6.2,
// AGENTS.md area slugs) plus the workspace package names, so a commit scope always
// maps either to a board component or to a concrete package/app in the monorepo.
const AREA_SCOPES = [
  "chart-engine",
  "charting-ui",
  "order-flow",
  "oms-execution",
  "rule-engine",
  "paper-trading",
  "accounts-admin",
  "auth-rbac",
  "ingestion",
  "recorder-replay",
  "journal-analytics",
  "backend-platform",
  "frontend-platform",
  "electron-shell",
  "design-system",
  "infra-devops",
  "docs",
];

// Legacy/ticket-body component values (E02-T07 body) kept for compatibility with
// tickets authored before the area/* slugs were finalised.
const COMPONENT_SCOPES = [
  "chart-engine",
  "data-feeds",
  "indicators",
  "drawing-tools",
  "alerts",
  "backtesting",
  "scripting",
  "web",
  "api",
  "auth",
  "collaboration",
  "infra",
  "docs",
];

// Workspace package/app names — extend as apps/* and packages/* grow.
const PACKAGE_SCOPES = ["config", "ui", "protocol", "fixtures", "chart-engine"];

const ALLOWED_SCOPES = Array.from(
  new Set([...AREA_SCOPES, ...COMPONENT_SCOPES, ...PACKAGE_SCOPES]),
);

module.exports = {
  extends: ["@commitlint/config-conventional"],
  rules: {
    "type-enum": [
      2,
      "always",
      ["feat", "fix", "chore", "docs", "test", "refactor", "perf", "build", "ci"],
    ],
    "scope-enum": [2, "always", ALLOWED_SCOPES],
    "scope-empty": [2, "never"],
    "subject-max-length": [2, "always", 100],
    "subject-case": [0],
  },
};
