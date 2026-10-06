#!/bin/sh
# temp: run all cv-* semgrep packs (deleted after use)
set -e
cd "$(dirname "$0")"
args=""
for f in ../../.semgrep/cv-*.yml; do args="$args --config $f"; done
semgrep scan $args --quiet candleviewer/alerts candleviewer/storage candleviewer/app.py candleviewer/observability
