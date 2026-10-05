// Redaction gate for packages/fixtures (E02-T03 placeholder; real fixtures
// land in E08). Fails if any file under raw/ or golden/ looks like it
// contains a credential (API key, signature, PEM block, bearer token).
// This is the control named in the ticket's Security notes for the
// "recorded fixture leaks credentials" threat (E02-X01).
import { readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join, relative } from "node:path";

const __dirname = dirname(fileURLToPath(import.meta.url));
const packageRoot = join(__dirname, "..");
// E08-T05: `bybit/` is the shared recorded corpus (packages/fixtures/bybit/<date>/).
const scanDirs = ["raw", "golden", "bybit"].map((d) => join(packageRoot, d));

const SECRET_PATTERNS = [
  { name: "PEM private key block", re: /-----BEGIN [A-Z ]*PRIVATE KEY-----/ },
  { name: "bearer token", re: /Bearer\s+[A-Za-z0-9._-]{20,}/ },
  {
    name: "Bybit-style api key/secret field",
    re: /"(api[_-]?key|api[_-]?secret|sign|signature)"\s*:\s*"[^"]{8,}"/i,
  },
  {
    name: "generic long hex/base64 secret-shaped field",
    re: /"(secret|token|password)"\s*:\s*"[A-Za-z0-9+/=_-]{16,}"/i,
  },
  {
    // E08-X03: Bybit v5 auth headers, captured verbatim by a recorder that
    // did not redact them before the fixture was committed.
    name: "Bybit X-BAPI-* auth header",
    re: /X-BAPI-(API-KEY|SIGN)["']?\s*[:=]\s*["']?[A-Za-z0-9]{16,}/i,
  },
];

export function listFiles(dir) {
  let stat;
  try {
    stat = statSync(dir);
  } catch {
    return [];
  }
  if (!stat.isDirectory()) return [];
  const out = [];
  for (const entry of readdirSync(dir)) {
    if (entry === ".gitkeep") continue;
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      out.push(...listFiles(full));
    } else {
      out.push(full);
    }
  }
  return out;
}

export function scanForSecrets(files, readFile = (f) => readFileSync(f, "utf8")) {
  const findings = [];
  for (const file of files) {
    const content = readFile(file);
    for (const pattern of SECRET_PATTERNS) {
      if (pattern.re.test(content)) {
        findings.push({ file, pattern: pattern.name });
      }
    }
  }
  return findings;
}

/**
 * Scans the given directories for secret-shaped content and returns the
 * findings without exiting the process (used by both the CLI and tests).
 */
export function verifyDirectories(dirs) {
  const files = dirs.flatMap(listFiles);
  const findings = scanForSecrets(files);
  return { files, findings };
}

function main() {
  const { files, findings } = verifyDirectories(scanDirs);
  if (findings.length > 0) {
    console.error(
      "[fixtures-verify] FAILED — possible credential leak(s):\n" +
        findings
          .map((f) => `  - ${relative(packageRoot, f.file)}: matched "${f.pattern}"`)
          .join("\n"),
    );
    process.exit(1);
  }
  console.log(`[fixtures-verify] OK (${files.length} file(s) scanned, no matches).`);
}

// Only run when executed directly (not when imported by tests importing
// `scanForSecrets`), so the test suite can exercise the pure function
// without triggering `process.exit`.
const isMain = process.argv[1] && import.meta.url === new URL(process.argv[1], "file://").href;
if (isMain) {
  main();
}
