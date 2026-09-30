"""Directory layout, dataset-id registry, and path resolution (SR-097).

`docs/plan/21-database-schema.md` Sec.5.1: the Hive-partitioned tree under
`CV_COLD_ROOT` plus the `_manifests/` sibling tree. This module owns *every*
path built from caller input — `ColdTierRepository.query`'s `dataset_id` is
resolved here, never a raw filesystem path, so path traversal and symlink
escape are structurally impossible rather than merely validated (SR-097).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from candleviewer.storage.models import StreamKind

#: Partition-key template per stream, per `21-database-schema.md` Sec.5.1's
#: worked tree. Every entry starts with `symbol=...` except `oms/*` datasets,
#: which are registered separately (out of scope for this ticket — see
#: ticket "Out of scope": "Journal/OMS export producers").
_PARTITION_TEMPLATES: dict[StreamKind, tuple[str, ...]] = {
    StreamKind.TRADES: ("symbol", "dt"),
    StreamKind.ORDERBOOK_DELTA: ("symbol", "dt", "hour"),
    StreamKind.ORDERBOOK_SNAPSHOT: ("symbol", "dt"),
    StreamKind.TICKERS: ("symbol", "dt"),
    StreamKind.KLINES: ("symbol", "interval", "ym"),
    StreamKind.LIQUIDATIONS: ("symbol", "dt"),
    StreamKind.OPEN_INTEREST: ("symbol", "ym"),
    StreamKind.FUNDING_RATES: ("symbol", "y"),
    StreamKind.BARS: ("family", "symbol", "bar_param", "ym"),
    StreamKind.FOOTPRINT_CELLS: ("symbol", "bar_family", "bar_param", "dt"),
    StreamKind.PROFILES: ("symbol", "profile_kind", "ym"),
    StreamKind.ORDERFLOW_METRICS: ("symbol", "dt"),
    StreamKind.HEATMAP_CELLS: ("symbol", "dt", "hour"),
}

#: The stream-directory name on disk — mirrors the enum value except where
#: the tree in Sec.5.1 uses a plural not matching the `StreamKind` value.
_STREAM_DIRS: dict[StreamKind, str] = {
    StreamKind.ORDERBOOK_DELTA: "orderbook_deltas",
    StreamKind.ORDERBOOK_SNAPSHOT: "orderbook_snapshots",
}


def stream_dir_name(stream: StreamKind) -> str:
    """The on-disk directory name for `stream` (registry-internal only)."""
    return _STREAM_DIRS.get(stream, stream.value)


class DatasetNotRegistered(ValueError):
    """Raised for any `dataset_id`/partition-key combination this registry
    does not recognise — the fail-closed default for SR-097."""


@dataclass(frozen=True, slots=True)
class ColdPaths:
    """Resolved, `CV_COLD_ROOT`-anchored paths for one stream partition.

    Every field is guaranteed (by `DatasetRegistry.resolve_partition`, the
    only constructor call site) to be a real descendant of `root` with no
    `..` segment and no symlink component — see that method's docstring.
    """

    root: Path
    partition_dir: Path
    manifests_dir: Path
    schema_registry_path: Path


class DatasetRegistry:
    """Resolves `(symbol, stream, partition_keys)` to filesystem paths under
    a fixed `CV_COLD_ROOT`, rejecting anything that is not a plain
    registered dataset id (SR-097 — "the registry rejects it, a path-
    traversal test asserts no filesystem read occurs outside CV_COLD_ROOT").

    Callers never pass a filesystem path — only a `StreamKind` (the
    registered dataset id) plus partition-key values, which are validated
    against a closed character set *before* any path is built.
    """

    #: Partition-value charset: no `/`, no `..`, no leading `.`, no drive
    #: letters/UNC prefixes — deliberately conservative over "technically
    #: safe" so a future stream addition cannot accidentally widen this.
    _SAFE_SEGMENT = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-=")

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve(strict=False)

    @property
    def root(self) -> Path:
        return self._root

    def _validate_segment(self, key: str, value: str) -> str:
        if not value or value in (".", "..") or any(c not in self._SAFE_SEGMENT for c in value):
            raise DatasetNotRegistered(f"unsafe partition value for {key!r}: {value!r}")
        return value

    def resolve_partition(
        self, stream: StreamKind, *, partition_values: dict[str, str]
    ) -> ColdPaths:
        """Build the partition directory for `stream` from named partition
        key/value pairs, validating every value and the final resolved path.

        Raises `DatasetNotRegistered` for an unknown stream, a missing
        partition key, an unsafe value, or a resolved path that escapes
        `root` (covers `..`, absolute overrides, and symlink escapes once
        the directory exists — checked again by `_assert_within_root`).
        """
        template = _PARTITION_TEMPLATES.get(stream)
        if template is None:
            raise DatasetNotRegistered(f"unregistered stream: {stream!r}")

        parts: list[str] = [stream_dir_name(stream)]
        for key in template:
            if key not in partition_values:
                raise DatasetNotRegistered(f"missing partition key {key!r} for {stream!r}")
            value = self._validate_segment(key, partition_values[key])
            parts.append(f"{key}={value}")

        partition_dir = self._root.joinpath(*parts)
        self._assert_within_root(partition_dir)
        return ColdPaths(
            root=self._root,
            partition_dir=partition_dir,
            manifests_dir=self._root / "_manifests",
            schema_registry_path=self._root / "_manifests" / "schema-registry.json",
        )

    def _assert_within_root(self, candidate: Path) -> None:
        """Resolve `candidate` (following any existing symlinks) and assert
        the result is still a descendant of `root` — the second half of
        SR-097's guarantee, covering a symlinked partition directory planted
        after registration."""
        resolved = candidate.resolve(strict=False)
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise DatasetNotRegistered(
                f"resolved path {resolved} escapes CV_COLD_ROOT {self._root}"
            ) from exc

    def dataset_glob(self, stream: StreamKind) -> str:
        """The `read_parquet(..., hive_partitioning=true)` glob for `stream`,
        used only by `duckdb_views.py` (never by `query()`'s dataset-id path)."""
        if stream not in _PARTITION_TEMPLATES:
            raise DatasetNotRegistered(f"unregistered stream: {stream!r}")
        depth = len(_PARTITION_TEMPLATES[stream])
        stars = "/".join(["*"] * depth)
        return str(self._root / stream_dir_name(stream) / stars / "*.parquet")

    def ensure_tree(self) -> None:
        """Create `root` and `_manifests/` if absent (idempotent)."""
        self._root.mkdir(parents=True, exist_ok=True)
        (self._root / "_manifests").mkdir(parents=True, exist_ok=True)

    def manifested_partitions(self, stream: StreamKind, symbol: str) -> list[ColdPaths]:
        """Partitions of `(stream, symbol)` that have a manifest document,
        discovered from `_manifests/` (never from caller text); each is
        re-resolved through `resolve_partition` so SR-097 checks apply."""
        template = partition_template(stream)
        self._validate_segment("symbol", symbol)
        base = self._root / "_manifests" / stream_dir_name(stream)
        out: list[ColdPaths] = []
        if not base.is_dir():
            return out
        for doc in sorted(base.rglob("*.json")):
            rel = doc.relative_to(base).with_suffix("")
            pairs = dict(p.split("=", 1) for p in rel.parts if "=" in p)
            if len(pairs) != len(rel.parts) or tuple(pairs) != template:
                continue
            if pairs.get("symbol") != symbol:
                continue
            try:
                out.append(self.resolve_partition(stream, partition_values=pairs))
            except DatasetNotRegistered:
                continue
        return out


def partition_template(stream: StreamKind) -> tuple[str, ...]:
    """The registered partition keys for `stream` (raises if unregistered)."""
    try:
        return _PARTITION_TEMPLATES[stream]
    except KeyError as exc:
        raise DatasetNotRegistered(f"unregistered stream: {stream!r}") from exc
