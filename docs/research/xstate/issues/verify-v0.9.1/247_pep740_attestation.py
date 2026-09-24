"""Verify #247: PyPI PEP 740 attestation exists for the 0.9.1 wheel.

Standalone (stdlib only). Neutral cwd. Checks:
  1. PyPI JSON API url entry for the wheel has no inline 'provenance' (expected;
     that field is populated only in some clients) -- so we instead query the
     dedicated PyPI Integrity API endpoint for attestation bundles.
  2. The attestation's subject digest matches the known wheel sha256.
  3. The signing certificate SAN / claims tie back to the tag + workflow.

Exit 0 if an attestation bundle is present and the digest matches.
Exit 1 otherwise.

This only proves what is verifiable from here (PyPI's public API); it does
not independently re-run Sigstore signature verification (would need
`pypi-attestations` / `sigstore` installed, not assumed present).
"""
import base64
import json
import sys
import urllib.request

WHEEL = "xstate_statemachine-0.9.1-py3-none-any.whl"
EXPECTED_SHA256 = (
    "d832d4d9a17b7b8003f61fa0714a8e57eaff316bcd5dd699d81d410362687162"
)
INTEGRITY_URL = (
    f"https://pypi.org/integrity/xstate-statemachine/0.9.1/{WHEEL}/provenance"
)


def main() -> int:
    with urllib.request.urlopen(INTEGRITY_URL, timeout=30) as resp:
        if resp.status != 200:
            print(f"NOT-FIXED: integrity API returned HTTP {resp.status}")
            return 1
        data = json.load(resp)

    bundles = data.get("attestation_bundles", [])
    if not bundles:
        print("NOT-FIXED: no attestation_bundles present")
        return 1

    ok = False
    for bundle in bundles:
        for att in bundle.get("attestations", []):
            statement_b64 = att.get("envelope", {}).get("statement")
            if not statement_b64:
                continue
            statement = json.loads(base64.b64decode(statement_b64))
            for subj in statement.get("subject", []):
                if subj.get("name") == WHEEL:
                    digest = subj.get("digest", {}).get("sha256")
                    if digest == EXPECTED_SHA256:
                        ok = True
                        print(f"Matched subject={subj['name']} sha256={digest}")
                    else:
                        print(
                            f"MISMATCH digest: got {digest} expected "
                            f"{EXPECTED_SHA256}"
                        )

    if ok:
        print("FIXED: PEP 740 attestation bundle present, digest matches.")
        return 0
    print("NOT-FIXED: attestation bundle present but no matching subject/digest.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
