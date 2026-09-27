# ==========================================================================
# GENERATED FILE — DO NOT EDIT BY HAND.
# Regenerate with `pnpm generate` (see docs/plan/22-api-openapi.yaml,
# docs/plan/23-ws-protocol.md / docs/plan/ws-schema.json). Hand edits are
# rejected by the header-guard lint (packages/protocol/scripts/check-
# generated-guard.mjs pattern; Python-side guard: this header + CI diff).
# Generator: datamodel-code-generator (pydantic_v2.BaseModel), pinned in
# services/api/pyproject.toml [dependency-groups.dev].
# ==========================================================================
from __future__ import annotations

from decimal import Decimal as PyDecimal
from decimal import InvalidOperation
from typing import Annotated

from pydantic import BeforeValidator, PlainSerializer

from enum import Enum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, RootModel


def _cv_parse_decimal(v: object) -> object:
    """Parses a wire-format decimal string; pydantic wraps a raised ValueError
    into its own ValidationError (a bare decimal.InvalidOperation would not
    be recognised as a validation failure and would propagate as a 500)."""
    if not isinstance(v, str):
        return v
    try:
        return PyDecimal(v)
    except InvalidOperation as exc:
        raise ValueError(f"invalid decimal string: {v!r}") from exc


Decimal = Annotated[
    PyDecimal,
    BeforeValidator(_cv_parse_decimal),
    PlainSerializer(lambda v: format(v, "f"), return_type=str),
]
"""Arbitrary-precision decimal transported as a string (convention C6)."""



class Symbol(RootModel[str]):
    root: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')


class EpochMs(RootModel[int]):
    root: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class Topic(RootModel[str]):
    root: str = Field(..., max_length=120, min_length=1, pattern='^[a-z_]+(\\.[A-Za-z0-9:_-]+)*$')


class Environment(Enum):
    live = 'live'
    demo = 'demo'
    testnet = 'testnet'


class Side(Enum):
    buy = 'buy'
    sell = 'sell'


class BarType(Enum):
    time = 'time'
    tick = 'tick'
    volume = 'volume'
    range = 'range'
    delta = 'delta'
    renko = 'renko'
    pnf = 'pnf'
    heikin_ashi = 'heikin_ashi'


class Depth(Enum):
    int_1 = 1
    int_50 = 50
    int_200 = 200
    int_500 = 500


class ErrorCode(Enum):
    protocol_violation = 'protocol_violation'
    frame_malformed = 'frame_malformed'
    unsupported_protocol = 'unsupported_protocol'
    not_authenticated = 'not_authenticated'
    auth_failed = 'auth_failed'
    auth_timeout = 'auth_timeout'
    token_expired = 'token_expired'
    user_disabled = 'user_disabled'
    forbidden = 'forbidden'
    account_scope_denied = 'account_scope_denied'
    unknown_topic = 'unknown_topic'
    invalid_topic_format = 'invalid_topic_format'
    unsupported_symbol = 'unsupported_symbol'
    invalid_options = 'invalid_options'
    encoding_unsupported = 'encoding_unsupported'
    subscription_limit = 'subscription_limit'
    too_many_topics = 'too_many_topics'
    duplicate_subscription = 'duplicate_subscription'
    not_subscribed = 'not_subscribed'
    resync_rate_limited = 'resync_rate_limited'
    client_rate_limited = 'client_rate_limited'
    slow_consumer = 'slow_consumer'
    no_data_recorded = 'no_data_recorded'
    degraded_data = 'degraded_data'
    exchange_unavailable = 'exchange_unavailable'
    replay_session_not_found = 'replay_session_not_found'
    replay_session_ended = 'replay_session_ended'
    internal_error = 'internal_error'


class Error(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    code: ErrorCode
    message: str = Field(..., max_length=1000)
    retryable: bool | None = False
    field: str | None = None
    request_id: str | None = None
    close: bool | None = False


class Reason(Enum):
    initial = 'initial'
    client_resync = 'client_resync'
    upstream_desync = 'upstream_desync'
    upstream_reconnect = 'upstream_reconnect'
    backpressure = 'backpressure'
    reconfigure = 'reconfigure'
    instrument_revision = 'instrument_revision'
    replay_seek = 'replay_seek'


class Source(Enum):
    live = 'live'
    replay = 'replay'


class SnapMeta(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    reason: Reason | None = None
    previous_seq: int | None = Field(None, ge=0)
    recording_started_at_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    history_bars: int | None = Field(None, ge=0)
    source: Source | None = 'live'


class T(Enum):
    hello = 'hello'
    welcome = 'welcome'
    auth = 'auth'
    auth_ok = 'auth_ok'
    sub = 'sub'
    sub_ok = 'sub_ok'
    unsub = 'unsub'
    unsub_ok = 'unsub_ok'
    snap = 'snap'
    d = 'd'
    resync = 'resync'
    revoked = 'revoked'
    ping = 'ping'
    pong = 'pong'
    err = 'err'
    ctl = 'ctl'
    ctl_ok = 'ctl_ok'
    bye = 'bye'


class E(Enum):
    j = 'j'
    b = 'b'
    b64 = 'b64'


class Envelope(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    t: T
    id: str | None = Field(None, description='Correlation id; echoed on replies.', max_length=64)
    ch: str | None = Field(
        None, max_length=120, min_length=1, pattern='^[a-z_]+(\\.[A-Za-z0-9:_-]+)*$'
    )
    s: int | None = Field(None, ge=0)
    ts: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    wt: int | None = Field(
        None,
        description='Wall-clock send time; present only on replay frames where `ts` is the recorded time.',
        ge=0,
    )
    rs: UUID | None = Field(None, description='Replay session id; present only on replay frames.')
    e: E | None = 'j'
    meta: SnapMeta | None = None
    p: Any | None = None


class Shell(Enum):
    electron = 'electron'
    browser = 'browser'
    other = 'other'


class Encoding(Enum):
    binary = 'binary'
    structured = 'structured'


class Capability(Enum):
    binary_book = 'binary_book'
    binary_bars = 'binary_bars'
    binary_trades = 'binary_trades'
    binary_footprint = 'binary_footprint'
    binary_heatmap = 'binary_heatmap'
    coalescing = 'coalescing'
    replay = 'replay'
    partial_snapshots = 'partial_snapshots'


class Hello(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    client: str = Field(..., max_length=60)
    client_version: str = Field(..., max_length=32)
    shell: Shell | None = None
    protocol: Literal['cv.v1']
    encodings: list[Encoding] | None = None
    capabilities: list[Capability] | None = None
    locale: str | None = Field(None, max_length=16)
    clock_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)


class Encoding1(Enum):
    msgpack = 'msgpack'
    json = 'json'


class Heartbeat1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    interval_ms: int = Field(..., ge=1000, le=120000)
    timeout_ms: int = Field(..., ge=5000, le=300000)


class Limits(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    max_subscriptions: int
    max_topics_per_request: int
    max_inbound_frame_bytes: int
    max_outbound_frame_bytes: int
    min_throttle_ms: int
    max_symbols_per_connection: int | None = None


class Welcome(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    protocol: Literal['cv.v1']
    encoding: Encoding1
    server_version: str
    git_sha: str | None = None
    connection_id: str
    server_time_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    clock_skew_ms: int | None = None
    auth_required: bool
    auth_timeout_ms: int | None = Field(None, ge=1000, le=60000)
    heartbeat: Heartbeat1
    limits: Limits
    features: dict[str, bool] | None = None


class Auth(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    access_token: str = Field(..., max_length=4096, min_length=20)
    environments: list[Environment] | None = Field(
        None,
        description="Environments this connection intends to observe; intersected with the token's grants.",
    )


class Role(Enum):
    owner = 'owner'
    manager = 'manager'
    viewer = 'viewer'


class Result(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    ch: str = Field(..., max_length=120, min_length=1, pattern='^[a-z_]+(\\.[A-Za-z0-9:_-]+)*$')
    ok: bool
    sub_id: str | None = None
    snapshot_pending: bool | None = None
    snapshot_forced: bool | None = None
    effective: dict[str, Any] | None = None
    warning: Error | None = None
    error: Error | None = None


class SubOk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    results: list[Result]


class Unsub(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    topics: list[Topic] = Field(..., max_length=50, min_length=1)


class Result1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    ch: str = Field(..., max_length=120, min_length=1, pattern='^[a-z_]+(\\.[A-Za-z0-9:_-]+)*$')
    ok: bool
    noop: bool | None = None


class UnsubOk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    results: list[Result1]


class TimeBucketMs(Enum):
    int_100 = 100
    int_250 = 250
    int_500 = 500
    int_1000 = 1000
    int_5000 = 5000


class Ctl(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    throttle_ms: int | None = Field(None, ge=0, le=60000)
    coalesce: bool | None = None
    depth: Depth | None = None
    price_grouping: int | None = Field(None, ge=1, le=1000)
    metrics: list[str] | None = None
    min_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    time_bucket_ms: TimeBucketMs | None = Field(
        None, description='Re-derived bucket (§6.1.1); triggers `resnapshot: true`.'
    )
    paused: bool | None = Field(
        None, description='Client-side pause; the server stops emitting but keeps state.'
    )


class CtlOk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    effective: dict[str, Any]
    resnapshot: bool | None = Field(
        False, description='When true, a fresh `snap` follows and prior state must be discarded.'
    )


class Reason1(Enum):
    sequence_gap = 'sequence_gap'
    decode_error = 'decode_error'
    state_corrupt = 'state_corrupt'
    client_restart = 'client_restart'
    manual = 'manual'


class Resync(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    last_seq: int | None = Field(None, ge=0)
    reason: Reason1


class Reason2(Enum):
    permission_revoked = 'permission_revoked'
    account_scope_changed = 'account_scope_changed'
    user_disabled = 'user_disabled'
    session_revoked = 'session_revoked'
    key_revoked = 'key_revoked'
    account_disabled = 'account_disabled'
    replay_session_ended = 'replay_session_ended'
    resync_rate_limited = 'resync_rate_limited'
    topic_removed = 'topic_removed'


class Revoked(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    reason: Reason2
    message: str
    removed_accounts: list[UUID] | None = None
    resubscribe_allowed: bool | None = False


class Heartbeat(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    client_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    server_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    rtt_hint_ms: int | None = Field(None, ge=0)


class Code(Enum):
    int_1000 = 1000
    int_1001 = 1001
    int_1002 = 1002
    int_1009 = 1009
    int_1011 = 1011
    int_1013 = 1013
    int_4400 = 4400
    int_4401 = 4401
    int_4403 = 4403
    int_4429 = 4429


class Hint(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    most_expensive_topics: list[Topic] | None = None


class Bye(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    code: Code
    reason: str = Field(..., max_length=64)
    message: str = Field(..., max_length=1000)
    retry_after_ms: int | None = Field(None, ge=0)
    reconnect: bool | None = None
    hint: Hint | None = None


class TickDirection(Enum):
    PlusTick = 'PlusTick'
    ZeroPlusTick = 'ZeroPlusTick'
    MinusTick = 'MinusTick'
    ZeroMinusTick = 'ZeroMinusTick'


class Trade(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: str | None = None
    ts_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    size: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    side: Side = Field(..., description='Taker/aggressor side, taken directly from Bybit `S`.')
    is_block_trade: bool | None = False
    is_liquidation: bool | None = False
    cluster_size: int | None = Field(1, ge=1)
    tick_direction: TickDirection | None = None


class Trades(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    trades: list[Trade]
    dropped: int | None = Field(
        None,
        description='Prints filtered out by `min_size` since the previous frame; never silent.',
        ge=0,
    )


class Bar(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    t_ms: int = Field(..., description='Bar open time.', ge=0)
    close_t_ms: int | None = Field(None, description='Present for non-time bars.', ge=0)
    o: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    h: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    l: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    c: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    v: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    turnover: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    trades: int | None = Field(None, ge=0)
    confirm: bool = Field(
        ..., description='False for the in-progress bar. A client MUST NOT treat it as closed.'
    )
    delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cvd: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    min_delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Bars(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    bar_type: BarType
    param: str = Field(..., max_length=24)
    bars: list[Bar]
    coalesced: bool | None = False
    coalesced_count: int | None = Field(None, ge=1)


class UnfinishedAuction(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    high: bool | None = None
    low: bool | None = None


class Cell(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bid_volume: str = Field(
        ...,
        description='Volume traded into the bid (taker sells).',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ask_volume: str = Field(
        ...,
        description='Volume traded into the ask (taker buys).',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    total_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    trades: int | None = Field(None, ge=0)
    is_poc: bool | None = False


class Imbalance(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    direction: Side
    ratio: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    stacked: bool | None = False
    stack_size: int | None = Field(None, ge=1)
    estimated: bool | None = False


class Bar1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    t_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    close_t_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    confirm: bool | None = None
    poc_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_high: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_low: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unfinished_auction: UnfinishedAuction | None = None
    cells: list[Cell]
    imbalances: list[Imbalance] | None = None


class Footprint(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    bar_type: BarType
    param: str = Field(..., max_length=24)
    tick_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_grouping: int | None = Field(None, ge=1)
    bars: list[Bar1]
    coalesced: bool | None = False
    coalesced_count: int | None = Field(None, ge=1)


class Bid(RootModel[float]):
    root: float = Field(..., ge=0.0)


class Ask(RootModel[float]):
    root: float = Field(..., ge=0.0)


class Column(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    t_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    price_min: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_step: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bids: list[Bid] = Field(
        ..., description='Resting bid size per price row, ascending from `price_min`.'
    )
    asks: list[Ask]
    complete: bool | None = Field(
        None, description='False while the time bucket is still accumulating.'
    )


class Heatmap(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    time_bucket_ms: TimeBucketMs = Field(
        ...,
        description='Effective bucket in force, echoing what the client derived per §6.1.1 (or 500 if the client sent none).',
    )
    price_grouping: int | None = Field(None, ge=1)
    depth: Depth | None = None
    columns: list[Column]
    max_value: float | None = None
    estimated: bool | None = False


class Kind(Enum):
    volume = 'volume'
    delta = 'delta'
    tpo = 'tpo'


class Split(Enum):
    composite = 'composite'
    session = 'session'
    fixed = 'fixed'


class Row(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    volume: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    buy_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    sell_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tpo_count: int | None = Field(None, ge=0)


class Profile1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    period_start_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    period_end_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    total_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    poc_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_high: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_low: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    naked_poc: bool | None = None
    rows: list[Row]
    hvn: list[Decimal] | None = None
    lvn: list[Decimal] | None = None


class Profile(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    kind: Kind
    split: Split | None = None
    profiles: list[Profile1]


class Metric(Enum):
    cvd = 'cvd'
    delta = 'delta'
    min_max_delta = 'min_max_delta'
    trades_per_sec = 'trades_per_sec'
    volume_per_sec = 'volume_per_sec'
    book_updates_per_sec = 'book_updates_per_sec'
    tape_acceleration = 'tape_acceleration'
    imbalance_ratio = 'imbalance_ratio'
    absorption = 'absorption'
    exhaustion = 'exhaustion'
    iceberg = 'iceberg'
    stop_run = 'stop_run'
    adx = 'adx'
    atr = 'atr'
    hurst = 'hurst'
    regime = 'regime'
    vwap = 'vwap'
    open_interest_delta = 'open_interest_delta'
    funding_basis = 'funding_basis'
    liquidation_intensity = 'liquidation_intensity'


class Unit(Enum):
    base_volume = 'base_volume'
    index = 'index'
    ratio = 'ratio'
    confidence = 'confidence'
    usd = 'usd'
    price = 'price'
    count = 'count'


class Series(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    metric: Metric
    t_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    v: Decimal | None
    unit: Unit | None = None
    estimated: bool | None = Field(
        False, description='True for heuristic metrics (iceberg, stop_run, absorption, exhaustion).'
    )
    params: dict[str, Any] | None = None
    meta: dict[str, Any] | None = Field(
        None, description='Event detail for event-like metrics, e.g. {price, side, reloads}.'
    )


class Metrics(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    bar_type: BarType | None = None
    param: str | None = None
    series: list[Series]


class Ticker1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    last_price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    mark_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    index_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bid1_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bid1_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ask1_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ask1_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_change_pct_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    high_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    low_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    volume_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    turnover_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_interest: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_interest_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    funding_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    next_funding_time_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    ts_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    stale: bool | None = False


class Ticker(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    tickers: list[Ticker1]


class Liquidation(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    ts_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    side: Side
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    size: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cluster_size: int | None = Field(1, ge=1)


class Liquidations(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    liquidations: list[Liquidation]
    note: str | None = Field(
        None,
        description='Bybit batches at most one allLiquidation push per symbol per 500 ms; counts are lower bounds.',
    )


class OrderType(Enum):
    market = 'market'
    limit = 'limit'


class Intent(Enum):
    entry = 'entry'
    stop_loss = 'stop_loss'
    take_profit = 'take_profit'
    scale_in = 'scale_in'
    scale_out = 'scale_out'
    flatten = 'flatten'
    reverse = 'reverse'
    algo_child = 'algo_child'


class State(Enum):
    new = 'new'
    pending_submit = 'pending_submit'
    submitted = 'submitted'
    accepted = 'accepted'
    partially_filled = 'partially_filled'
    filled = 'filled'
    pending_cancel = 'pending_cancel'
    cancelled = 'cancelled'
    pending_amend = 'pending_amend'
    rejected = 'rejected'
    expired = 'expired'
    untracked = 'untracked'


class TimeInForce(Enum):
    GTC = 'GTC'
    IOC = 'IOC'
    FOK = 'FOK'
    PostOnly = 'PostOnly'


class PositionIdx(Enum):
    int_0 = 0
    int_1 = 1
    int_2 = 2


class TriggerBy(Enum):
    LastPrice = 'LastPrice'
    MarkPrice = 'MarkPrice'
    IndexPrice = 'IndexPrice'
    NoneType_None = None


class TriggerDirection(Enum):
    rise = 'rise'
    fall = 'fall'
    NoneType_None = None


class TpslMode(Enum):
    Full = 'Full'
    Partial = 'Partial'


class AlgoKind(Enum):
    none = 'none'
    oco = 'oco'
    iceberg = 'iceberg'
    twap = 'twap'
    chase = 'chase'
    scaled = 'scaled'
    bracket = 'bracket'


class Change(Enum):
    created = 'created'
    submitted = 'submitted'
    ack = 'ack'
    fill = 'fill'
    amend = 'amend'
    cancel = 'cancel'
    reject = 'reject'
    expire = 'expire'
    reconcile = 'reconcile'


class Order(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: UUID
    exchange_account_id: UUID
    trade_group_id: UUID | None = None
    trade_group_leg_id: UUID | None = None
    parent_order_id: UUID | None = None
    order_link_id: str | None = Field(None, max_length=36)
    exchange_order_id: str | None = None
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    side: Side | None = None
    order_type: OrderType | None = None
    intent: Intent | None = None
    state: State
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    filled_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    remaining_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price: Decimal | None = None
    avg_fill_price: Decimal | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool | None = None
    close_on_trigger: bool | None = None
    position_idx: PositionIdx | None = None
    trigger_price: Decimal | None = None
    trigger_by: TriggerBy | None = None
    trigger_direction: TriggerDirection | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tpsl_mode: TpslMode | None = None
    algo_kind: AlgoKind | None = None
    environment: Environment | None = None
    is_paper: bool | None = Field(
        False,
        description='True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.',
    )
    rejected_reason: str | None = None
    change: Change | None = Field(
        None,
        description='What caused this frame; drives UI animation and the order-timeline widget.',
    )
    updated_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class Orders(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    orders: list[Order]
    removed: list[UUID] | None = Field(
        None,
        description='Order ids that left the open set (terminal state) and may be dropped from the live view.',
    )


class Side1(Enum):
    long = 'long'
    short = 'short'
    flat = 'flat'


class MarginMode(Enum):
    cross = 'cross'
    isolated = 'isolated'
    portfolio = 'portfolio'


class Position(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: UUID
    exchange_account_id: UUID
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    side: Side1
    position_idx: PositionIdx | None = None
    size: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    mark_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    position_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    leverage: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    margin_mode: MarginMode | None = None
    unrealised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl_session: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    liq_price: Decimal | None = None
    bust_price: Decimal | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop: str | None = Field(
        None,
        description='Price distance, not a percentage (Bybit semantics).',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tpsl_mode: TpslMode | None = None
    native_stop_present: bool | None = Field(
        None,
        description='False violates the safety invariant (arch P4); the OMS re-asserts the stop and raises a critical alert.',
    )
    trade_group_id: UUID | None = None
    r_multiple: Decimal | None = None
    environment: Environment | None = None
    is_paper: bool | None = Field(
        False,
        description='True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.',
    )
    updated_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class Positions(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    positions: list[Position]
    removed: list[UUID] | None = Field(None, description='Positions that went flat.')


class ExecType(Enum):
    Trade = 'Trade'
    AdlTrade = 'AdlTrade'
    Funding = 'Funding'
    BustTrade = 'BustTrade'
    Settle = 'Settle'


class Execution(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: UUID
    exec_id: str = Field(..., description='Exchange fill id; unique, used for dedupe.')
    order_id: UUID
    exchange_account_id: UUID
    trade_group_id: UUID | None = None
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    side: Side
    exec_qty: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    exec_price: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    exec_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fee: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fee_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fee_coin: str | None = None
    is_maker: bool | None = None
    exec_type: ExecType | None = None
    exec_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    environment: Environment | None = None
    is_paper: bool | None = Field(
        False,
        description='True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.',
    )
    ts_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class Executions(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    executions: list[Execution]


class RiskCapUsage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    daily_loss_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    daily_loss_limit_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_positions: int | None = None
    max_open_positions: int | None = None
    locked_out_until_ms: EpochMs | None = None


class Balance(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exchange_account_id: UUID
    coin: str
    equity: str = Field(
        ...,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    wallet_balance: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    available_balance: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unrealised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl_today: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    account_im_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    account_mm_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    risk_cap_usage: RiskCapUsage | None = Field(
        None,
        description="Live usage against the account profile's risk caps; drives the risk gauge.",
    )
    environment: Environment | None = None
    is_paper: bool | None = Field(
        False,
        description='True when the fill/order came from the paper matcher rather than the exchange. Mirrors the `is_paper` column.',
    )
    stale: bool | None = False
    updated_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class Wallet(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    balances: list[Balance]


class Status(Enum):
    draft = 'draft'
    submitting = 'submitting'
    partially_open = 'partially_open'
    open = 'open'
    closing = 'closing'
    closed = 'closed'
    failed = 'failed'
    cancelled = 'cancelled'


class Atomicity(Enum):
    best_effort = 'best_effort'
    all_or_none = 'all_or_none'


class Status1(Enum):
    pending = 'pending'
    submitted = 'submitted'
    rejected = 'rejected'
    open = 'open'
    partially_filled = 'partially_filled'
    filled = 'filled'
    cancelled = 'cancelled'
    closed = 'closed'
    error = 'error'


class Error1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    code: str
    message: str
    exchange_ret_code: int | None = None
    retryable: bool | None = None


class Leg(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: UUID
    exchange_account_id: UUID
    account_profile_id: UUID | None = None
    sequence_no: int | None = None
    status: Status1
    target_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    filled_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_entry_price: Decimal | None = None
    avg_exit_price: Decimal | None = None
    native_sl_confirmed: bool | None = None
    risk_usd: Decimal | None = None
    realised_pnl: Decimal | None = None
    fees_paid: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    error: Error1 | None = None


class Totals(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    requested_legs: int | None = None
    submitted_legs: int | None = None
    rejected_legs: int | None = None
    filled_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    target_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl: Decimal | None = None


class TradeGroup(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: UUID
    client_group_ref: str | None = None
    symbol: str | None = Field(None, pattern='^[A-Z0-9]{2,20}USDT$')
    side: Side | None = None
    intent: str | None = None
    status: Status
    atomicity: Atomicity | None = None
    algo_kind: AlgoKind | None = None
    rule_id: UUID | None = None
    legs: list[Leg] | None = None
    totals: Totals | None = None
    updated_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class TradeGroups(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    trade_groups: list[TradeGroup]


class Mode(Enum):
    disabled = 'disabled'
    simulate = 'simulate'
    armed = 'armed'


class LastRunStatus(Enum):
    running = 'running'
    ok = 'ok'
    error = 'error'
    aborted = 'aborted'
    throttled = 'throttled'
    NoneType_None = None


class Rule(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: UUID
    name: str | None = None
    mode: Mode
    active_version_id: UUID | None = None
    version: int | None = None
    last_run_status: LastRunStatus | None = None
    fire_count_24h: int | None = None
    next_eligible_fire_at_ms: EpochMs | None = Field(
        None, description='Set while a cooldown guard is active.'
    )
    updated_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)


class Kind1(Enum):
    evaluated = 'evaluated'
    suppressed = 'suppressed'
    action_sent = 'action_sent'
    action_result = 'action_result'
    error = 'error'
    started = 'started'
    finished = 'finished'


class Event(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    rule_id: UUID
    run_id: UUID
    kind: Kind1
    ts_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    payload: dict[str, Any] | None = None


class Rules(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    rules: list[Rule] | None = None
    events: list[Event] | None = Field(
        None, description='Present only when subscribed with include_events: true.'
    )


class Channel(Enum):
    in_app = 'in_app'
    email = 'email'
    webhook = 'webhook'
    push = 'push'
    desktop = 'desktop'


class Status2(Enum):
    queued = 'queued'
    sent = 'sent'
    failed = 'failed'
    suppressed = 'suppressed'
    acked = 'acked'


class Severity(Enum):
    debug = 'debug'
    info = 'info'
    warning = 'warning'
    error = 'error'
    critical = 'critical'


class Delivery(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    id: int
    alert_id: UUID
    channel: Channel
    status: Status2
    severity: Severity | None = None
    title: str | None = None
    message: str
    symbol: Symbol | None = None
    fired_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    acked_at_ms: EpochMs | None = None
    error: str | None = None


class Alerts(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    deliveries: list[Delivery]
    unacked_count: int | None = Field(None, ge=0)


class Overall(Enum):
    healthy = 'healthy'
    degraded = 'degraded'
    warning = 'warning'
    down = 'down'


class State1(Enum):
    connecting = 'connecting'
    connected = 'connected'
    degraded = 'degraded'
    disconnected = 'disconnected'


class Connection(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    endpoint: str | None = None
    state: State1 | None = None
    subscribed_topics: int | None = None
    reconnects_last_hour: int | None = None
    last_ping_ms: int | None = None


class State2(Enum):
    idle = 'idle'
    starting = 'starting'
    recording = 'recording'
    degraded = 'degraded'
    stopping = 'stopping'
    stopped = 'stopped'
    error = 'error'


class Reason3(Enum):
    manual = 'manual'
    chart_open = 'chart_open'
    position_open = 'position_open'
    rule_dependency = 'rule_dependency'
    alert_dependency = 'alert_dependency'


class Symbol1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    state: State2
    reason: Reason3 | None = None
    pinned: bool | None = None
    lag_ms: int | None = None
    rows_last_hour: int | None = None
    dropped_messages: int | None = Field(
        None, description='Non-zero is an incident, not a warning.'
    )
    resyncs_last_hour: int | None = None
    disk_bytes: int | None = None
    last_event_at_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)


class Storage(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    disk_free_bytes: int | None = None
    daily_growth_bytes: int | None = None
    projected_full_at_ms: EpochMs | None = None


class Recorder(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    overall: Overall
    connections: list[Connection] | None = None
    symbols: list[Symbol1]
    ingest_rate_msgs_per_sec: int | None = None
    write_backlog_rows: int | None = None
    storage: Storage | None = None


class Kind2(Enum):
    health = 'health'
    kill_switch = 'kill_switch'
    feature_flags = 'feature_flags'
    exchange_state = 'exchange_state'
    connection_quality = 'connection_quality'
    shutdown_notice = 'shutdown_notice'
    degraded_data = 'degraded_data'
    clock_drift = 'clock_drift'
    notice = 'notice'


class Health(Enum):
    healthy = 'healthy'
    degraded = 'degraded'
    warning = 'warning'
    down = 'down'


class State3(Enum):
    healthy = 'healthy'
    degraded = 'degraded'
    warning = 'warning'
    down = 'down'


class Component(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    name: str | None = None
    state: State3 | None = None
    detail: str | None = None


class Actions(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    orders_cancelled: int | None = None
    positions_flattened: int | None = None
    rules_disarmed: int | None = None


class PublicWs(Enum):
    connected = 'connected'
    connecting = 'connecting'
    resyncing = 'resyncing'
    disconnected = 'disconnected'


class PrivateWs(Enum):
    connected = 'connected'
    connecting = 'connecting'
    resyncing = 'resyncing'
    disconnected = 'disconnected'


class Rest(Enum):
    healthy = 'healthy'
    degraded = 'degraded'
    rate_limited = 'rate_limited'
    down = 'down'


class Exchange(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    public_ws: PublicWs | None = None
    private_ws: PrivateWs | None = None
    rest: Rest | None = None
    rate_budget_free_pct: float | None = Field(None, ge=0.0, le=100.0)


class Class(Enum):
    healthy = 'healthy'
    lagging = 'lagging'
    saturated = 'saturated'
    overflowing = 'overflowing'


class Applied(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    throttle_multiplier: float | None = None
    forced_coalesce: bool | None = None
    degraded_topics: list[Topic] | None = None


class Level(RootModel[list[Decimal]]):
    root: list[Decimal] = Field(..., max_length=2, min_length=2)


class Encoding2(Enum):
    binary = 'binary'
    structured = 'structured'


class SessionAnchor(Enum):
    utc_day = 'utc_day'
    funding_8h = 'funding_8h'
    custom = 'custom'


class Options(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    throttle_ms: int | None = Field(None, ge=0, le=60000)
    encoding: Encoding2 | None = None
    coalesce: bool | None = True
    from_seq: int | None = Field(None, ge=0)
    from_ts_ms: int | None = Field(None, description='Epoch milliseconds, UTC.', ge=0)
    min_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cluster_window_ms: int | None = Field(None, ge=0, le=5000)
    cluster_tolerance_ticks: int | None = Field(None, ge=0, le=20)
    include_delta: bool | None = None
    history: int | None = Field(None, ge=0, le=1000)
    price_grouping: int | None = Field(None, ge=1, le=1000)
    imbalance_ratio: float | None = Field(None, ge=1.5, le=20.0)
    min_stack: int | None = Field(None, ge=2, le=10)
    min_imbalance_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    time_bucket_ms: TimeBucketMs | None = Field(
        500,
        description='Client SHOULD derive this per §6.1.1 rather than sending a constant; 500 is the non-visual-client fallback.',
    )
    depth: Depth | None = None
    window_seconds: int | None = Field(None, ge=10, le=900)
    split: Split | None = None
    session_anchor: SessionAnchor | None = None
    value_area_pct: float | None = Field(None, ge=50.0, le=95.0)
    metrics: list[str] | None = Field(None, max_length=12, min_length=1)
    bar_type: BarType | None = None
    param: str | None = Field(None, max_length=24)
    params: dict[str, Any] | None = None
    exchange_account_ids: list[UUID] | None = Field(None, max_length=25)
    symbols: list[Symbol] | None = Field(None, max_length=40)
    open_only: bool | None = None
    status: list[str] | None = None
    rule_ids: list[UUID] | None = None
    include_events: bool | None = None
    unacked_only: bool | None = None
    min_notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal as a string; never a JSON number.',
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Scope(Enum):
    global_ = 'global'
    accounts = 'accounts'


class KillSwitch(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    engaged: bool
    scope: Scope
    exchange_account_ids: list[UUID] | None = None
    engaged_at_ms: EpochMs | None = None
    engaged_by: UUID | None = None
    engaged_by_username: str | None = None
    reason: str | None = None


class AuthOk(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    user_id: UUID
    username: str | None = None
    roles: list[Role]
    permissions: list[str]
    account_scope: list[UUID]
    allowed_environments: list[Environment] | None = None
    session_id: UUID
    token_expires_at_ms: int = Field(..., description='Epoch milliseconds, UTC.', ge=0)
    kill_switch: KillSwitch | None = None


class Topic1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    ch: str = Field(..., max_length=120, min_length=1, pattern='^[a-z_]+(\\.[A-Za-z0-9:_-]+)*$')
    opts: Options | None = None


class Sub(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    topics: list[Topic1] = Field(..., max_length=50, min_length=1)
    snapshot: bool | None = True
    replay_session_id: UUID | None = None


class Book(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(..., pattern='^[A-Z0-9]{2,20}USDT$')
    depth: Depth | None = None
    price_scale: int | None = Field(None, ge=0, le=18)
    qty_scale: int | None = Field(None, ge=0, le=18)
    xu: int | None = Field(None, description='Bybit orderbook update id `u`, for diagnostics only.')
    xseq: int | None = Field(None, description='Bybit cross-topic sequence `seq`.')
    bids: list[Level] = Field(..., description='Descending by price. Size "0" deletes the level.')
    asks: list[Level] = Field(..., description='Ascending by price. Size "0" deletes the level.')
    stale: bool | None = False
    coalesced: bool | None = False
    coalesced_count: int | None = Field(None, ge=1)


class System(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    kind: Kind2
    severity: Severity | None = None
    message: str | None = None
    health: Health | None = None
    components: list[Component] | None = None
    kill_switch: KillSwitch | None = None
    actions: Actions | None = None
    feature_flags: dict[str, Any] | None = None
    exchange: Exchange | None = None
    public_ws: PublicWs | None = None
    private_ws: PrivateWs | None = None
    affected_symbols: list[Symbol] | None = None
    class_: Class | None = Field(None, alias='class')
    queue_pct: float | None = Field(None, ge=0.0, le=100.0)
    rtt_ms: int | None = Field(None, ge=0)
    applied: Applied | None = None
    reason: str | None = None
    closing_in_ms: int | None = None
    expected_downtime_ms: int | None = None
    clock_offset_ms: int | None = None
    degraded_topics: list[Topic] | None = None


class Model(
    RootModel[
        Envelope
        | Hello
        | Welcome
        | Auth
        | AuthOk
        | Sub
        | SubOk
        | Unsub
        | UnsubOk
        | Ctl
        | CtlOk
        | Resync
        | Revoked
        | Heartbeat
        | Bye
        | Book
        | Trades
        | Bars
        | Footprint
        | Heatmap
        | Profile
        | Metrics
        | Ticker
        | Liquidations
        | Orders
        | Positions
        | Executions
        | Wallet
        | TradeGroups
        | Rules
        | Alerts
        | Recorder
        | System
        | Any
    ]
):
    root: (
        Envelope
        | Hello
        | Welcome
        | Auth
        | AuthOk
        | Sub
        | SubOk
        | Unsub
        | UnsubOk
        | Ctl
        | CtlOk
        | Resync
        | Revoked
        | Heartbeat
        | Bye
        | Book
        | Trades
        | Bars
        | Footprint
        | Heatmap
        | Profile
        | Metrics
        | Ticker
        | Liquidations
        | Orders
        | Positions
        | Executions
        | Wallet
        | TradeGroups
        | Rules
        | Alerts
        | Recorder
        | System
        | Any
    )
