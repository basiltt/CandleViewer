.PHONY: governance

# GOV-001 (CODEOWNERS coverage check) + GOV-002 (rule-reference link check) +
# GOV-003 (single-source-of-truth duplication check). Stdlib-only Python; runs
# before any package manager is scaffolded (E02). Wired into the `governance`
# job invoked by `pr-metadata` (job creation: E01-Q02). See CONSTITUTION.md
# C-16.4 / C-16.5, C-8.1 / C-10.1.
governance:
	python scripts/check_codeowners_coverage.py --repo-root .
	python scripts/check_rule_refs.py --repo-root .
	python scripts/check_sot_duplication.py --repo-root .
