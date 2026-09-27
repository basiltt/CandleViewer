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

from enum import Enum, IntEnum, StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import (
    AnyUrl,
    AwareDatetime,
    BaseModel,
    ConfigDict,
    EmailStr,
    Field,
    RootModel,
    SecretStr,
)


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
    root: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )


class ExchangeCode(StrEnum):
    """
    Exchange identifier. v1 supports Bybit only (locked scope: Bybit USDT linear perpetuals).
    Mirrors the Postgres type `exchange_code`; the adapter abstraction
    (`24-internal-schemas.md`) exists so a second value can be added without a breaking change.

    """

    bybit = 'bybit'


class Environment(StrEnum):
    """
    Structural environment selector (arch P9). Mirrors the Postgres type `exchange_env`.
    """

    live = 'live'
    demo = 'demo'
    testnet = 'testnet'


class Error(BaseModel):
    field: str | None = None
    rule: str | None = None
    message: str | None = None


class Exchange(BaseModel):
    """
    Present when the failure originated at Bybit.
    """

    ret_code: int | None = None
    ret_msg: str | None = None
    endpoint: str | None = None
    request_id: str | None = None


class Problem(BaseModel):
    """
    RFC 9457 problem detail. `code` mirrors the `x-error-codes` catalogue.
    """

    type: AnyUrl = Field(..., description='`https://candleviewer.local/errors/{code}`.')
    title: str
    status: int = Field(..., ge=400, le=599)
    detail: str | None = None
    instance: str | None = Field(
        None,
        description='Correlation id, `urn:cv:req:{uuid}`; matches the `X-Request-Id` header and the audit entry.',
    )
    code: str = Field(..., description='Stable machine-readable error code from `x-error-codes`.')
    errors: list[Error] | None = Field(None, description='Field-level validation failures.')
    required_permissions: list[str] | None = None
    retry_after_seconds: int | None = None
    exchange: Exchange | None = Field(
        None, description='Present when the failure originated at Bybit.'
    )


class PageMeta(BaseModel):
    next_cursor: str | None = None
    has_more: bool
    count: int = Field(
        ...,
        description='Items in this page (not the total, which is never computed for unbounded sets).',
    )
    total: int | None = Field(None, description='Present only where a cheap exact count exists.')


class Page(BaseModel):
    items: list[Any]
    meta: PageMeta


class Source(StrEnum):
    questdb = 'questdb'
    parquet = 'parquet'
    postgres = 'postgres'
    exchange_rest = 'exchange_rest'
    memory = 'memory'


class DataMeta(PageMeta):
    sources: list[Source] | None = Field(None, description='Storage tiers consulted.')
    recording_started_at: AwareDatetime | None = None
    generated_at: AwareDatetime | None = None


class UserStatus(StrEnum):
    invited = 'invited'
    active = 'active'
    disabled = 'disabled'
    locked = 'locked'


class RoleName(StrEnum):
    owner = 'owner'
    manager = 'manager'
    viewer = 'viewer'


class MfaMethodKind(StrEnum):
    totp = 'totp'
    webauthn = 'webauthn'
    recovery_code = 'recovery_code'


class AccountKind(StrEnum):
    main = 'main'
    sub = 'sub'


class KeyStatus(StrEnum):
    pending = 'pending'
    active = 'active'
    rotating = 'rotating'
    revoked = 'revoked'
    expired = 'expired'
    invalid = 'invalid'


class SizingMode(StrEnum):
    """
    How a request expresses order size.

    **Persistence contract.** The Postgres type `sizing_mode`
    (`21-database-schema.md` §Enums) holds only the four *resolved* modes
    `fixed_qty | fixed_notional | pct_equity | risk_based`. The two extra API values are
    **request-time sugar that never reaches the database**; the OMS resolves them before
    any row is written, and `orders.requested_qty_mode` / `account_profiles.sizing_mode`
    therefore always contain a resolved value:

    | API value | Resolution | Stored as |
    |---|---|---|
    | `pct_position` | `pct` % of the *current open position* qty on that symbol/account (scale-out, flatten-partial). Rejected with `validation_failed` if no position is open. | `fixed_qty` |
    | `profile` | Inherit the active `AccountProfile.sizing` block verbatim. | whatever the profile's own mode resolves to |

    Contract test `enum_parity_sizing_mode` asserts (a) the DB enum equals this enum minus
    `x-db-enum-superset`, and (b) no persisted row ever holds a superset value.

    """

    fixed_qty = 'fixed_qty'
    fixed_notional = 'fixed_notional'
    pct_equity = 'pct_equity'
    risk_based = 'risk_based'
    pct_position = 'pct_position'
    profile = 'profile'


class OffsetUnit(StrEnum):
    """
    Unit in which a stop/target distance is expressed.

    **Persistence contract.** The Postgres type `offset_unit` holds
    `ticks | percent | r_multiple | atr`. The API additionally accepts `price`, meaning
    "`value` is an absolute price level, not a distance"; the OMS converts it to a
    `ticks` distance from the resolved entry/reference price before persisting, so
    `account_profiles.sl_offset_unit` / `tp_offset_unit` never store `price`.
    Contract test `enum_parity_offset_unit` asserts this.

    """

    ticks = 'ticks'
    percent = 'percent'
    r_multiple = 'r_multiple'
    atr = 'atr'
    price = 'price'


class TradeGroupStatus(StrEnum):
    draft = 'draft'
    submitting = 'submitting'
    partially_open = 'partially_open'
    open = 'open'
    closing = 'closing'
    closed = 'closed'
    failed = 'failed'
    cancelled = 'cancelled'


class LegStatus(StrEnum):
    pending = 'pending'
    submitted = 'submitted'
    rejected = 'rejected'
    open = 'open'
    partially_filled = 'partially_filled'
    filled = 'filled'
    cancelled = 'cancelled'
    closed = 'closed'
    error = 'error'


class OrderIntent(StrEnum):
    entry = 'entry'
    stop_loss = 'stop_loss'
    take_profit = 'take_profit'
    scale_in = 'scale_in'
    scale_out = 'scale_out'
    flatten = 'flatten'
    reverse = 'reverse'
    algo_child = 'algo_child'


class OrderState(StrEnum):
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


class OrderType(StrEnum):
    market = 'market'
    limit = 'limit'


class OrderSide(StrEnum):
    buy = 'buy'
    sell = 'sell'


class TimeInForce(StrEnum):
    GTC = 'GTC'
    IOC = 'IOC'
    FOK = 'FOK'
    PostOnly = 'PostOnly'


class TriggerBy(StrEnum):
    LastPrice = 'LastPrice'
    MarkPrice = 'MarkPrice'
    IndexPrice = 'IndexPrice'


class TpSlMode(StrEnum):
    Full = 'Full'
    Partial = 'Partial'


class PositionMode(StrEnum):
    one_way = 'one_way'
    hedge = 'hedge'


class MarginMode(StrEnum):
    cross = 'cross'
    isolated = 'isolated'
    portfolio = 'portfolio'


class AlgoKind(StrEnum):
    none = 'none'
    oco = 'oco'
    iceberg = 'iceberg'
    twap = 'twap'
    chase = 'chase'
    scaled = 'scaled'
    bracket = 'bracket'


class RuleScope(StrEnum):
    global_ = 'global'
    account = 'account'
    symbol = 'symbol'
    position = 'position'
    trade_group = 'trade_group'


class RuleMode(StrEnum):
    disabled = 'disabled'
    simulate = 'simulate'
    armed = 'armed'


class RuleRunStatus(StrEnum):
    running = 'running'
    ok = 'ok'
    error = 'error'
    aborted = 'aborted'
    throttled = 'throttled'


class AlertChannel(StrEnum):
    in_app = 'in_app'
    email = 'email'
    webhook = 'webhook'
    push = 'push'
    desktop = 'desktop'


class DeliveryStatus(StrEnum):
    queued = 'queued'
    sent = 'sent'
    failed = 'failed'
    suppressed = 'suppressed'
    acked = 'acked'


class RecordingState(StrEnum):
    idle = 'idle'
    starting = 'starting'
    recording = 'recording'
    degraded = 'degraded'
    stopping = 'stopping'
    stopped = 'stopped'
    error = 'error'


class RecordReason(StrEnum):
    manual = 'manual'
    chart_open = 'chart_open'
    position_open = 'position_open'
    rule_dependency = 'rule_dependency'
    alert_dependency = 'alert_dependency'


class StreamKind(StrEnum):
    trades = 'trades'
    orderbook_delta = 'orderbook_delta'
    orderbook_snapshot = 'orderbook_snapshot'
    tickers = 'tickers'
    klines = 'klines'
    liquidations = 'liquidations'
    open_interest = 'open_interest'
    funding = 'funding'


class RetentionAction(StrEnum):
    drop = 'drop'
    archive_parquet = 'archive_parquet'
    downsample = 'downsample'
    pin = 'pin'


class ReplayState(StrEnum):
    created = 'created'
    buffering = 'buffering'
    playing = 'playing'
    paused = 'paused'
    finished = 'finished'
    error = 'error'


class JournalSide(StrEnum):
    long = 'long'
    short = 'short'


class FlagKind(StrEnum):
    boolean = 'boolean'
    percentage = 'percentage'
    variant = 'variant'


class AuditOutcome(StrEnum):
    success = 'success'
    failure = 'failure'
    denied = 'denied'


class Severity(StrEnum):
    debug = 'debug'
    info = 'info'
    warning = 'warning'
    error = 'error'
    critical = 'critical'


class BackupKind(StrEnum):
    pg_basebackup = 'pg_basebackup'
    pg_dump = 'pg_dump'
    questdb_snapshot = 'questdb_snapshot'
    parquet_sync = 'parquet_sync'
    config_bundle = 'config_bundle'


class BackupStatus(StrEnum):
    running = 'running'
    ok = 'ok'
    failed = 'failed'
    verified = 'verified'
    restored = 'restored'


class ComponentState(StrEnum):
    healthy = 'healthy'
    degraded = 'degraded'
    warning = 'warning'
    down = 'down'


class KlineInterval(StrEnum):
    """
    Bybit-compatible interval codes (minutes, or D/W/M).
    """

    field_1 = '1'
    field_3 = '3'
    field_5 = '5'
    field_15 = '15'
    field_30 = '30'
    field_60 = '60'
    field_120 = '120'
    field_240 = '240'
    field_360 = '360'
    field_720 = '720'
    D = 'D'
    W = 'W'
    M = 'M'


class BarType(StrEnum):
    time = 'time'
    tick = 'tick'
    volume = 'volume'
    range = 'range'
    delta = 'delta'
    renko = 'renko'
    pnf = 'pnf'
    heikin_ashi = 'heikin_ashi'


class MetricCode(StrEnum):
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


class LoginRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    identifier: str = Field(..., description='Username or email.', max_length=254, min_length=1)
    password: SecretStr = Field(..., max_length=512, min_length=1)
    device_name: str | None = Field(None, description='Shown in the session list.', max_length=120)


class TokenBundle(BaseModel):
    access_token: str
    token_type: Literal['Bearer']
    expires_in: int = Field(..., description='Access-token lifetime in seconds (600).')
    refresh_expires_in: int | None = Field(
        None, description='Refresh-token lifetime in seconds (2592000).'
    )
    refresh_token: str | None = Field(
        None,
        description='Returned only to non-cookie clients that set `cookie_auth:false` on login.',
    )


class MfaChallengeResponse(BaseModel):
    status: Literal['mfa_required']
    mfa_token: str
    methods: list[MfaMethodKind]
    expires_in: int
    webauthn_challenge: dict[str, Any] | None = None


class MfaVerifyRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    mfa_token: str
    method: MfaMethodKind
    code: str | None = Field(
        None, description='TOTP digits or a recovery code.', pattern='^[0-9A-Za-z-]{6,32}$'
    )
    webauthn_assertion: dict[str, Any] | None = None
    remember_device_days: int | None = Field(0, ge=0, le=30)


class Method(StrEnum):
    totp = 'totp'
    webauthn = 'webauthn'


class MfaEnrollRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    method: Method
    label: str | None = Field(None, max_length=60)


class MfaEnrollResponse(BaseModel):
    method_id: UUID
    method: MfaMethodKind
    otpauth_uri: str | None = None
    webauthn_creation_options: dict[str, Any] | None = None
    recovery_codes: list[str] | None = Field(
        None, description='Shown exactly once, on first enrolment.'
    )


class MfaEnrollConfirmRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    method_id: UUID
    code: str | None = None
    webauthn_attestation: dict[str, Any] | None = None


class MfaMethod(BaseModel):
    id: UUID | None = None
    kind: MfaMethodKind | None = None
    label: str | None = None
    active: bool | None = None
    created_at: AwareDatetime | None = None
    last_used_at: AwareDatetime | None = None


class RefreshRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    refresh_token: str | None = Field(None, description='Only for clients that cannot use cookies.')


class ChangePasswordRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    current_password: SecretStr
    new_password: SecretStr = Field(..., max_length=512, min_length=12)


class UserSession(BaseModel):
    id: UUID | None = None
    device_name: str | None = None
    ip: str | None = None
    user_agent: str | None = None
    created_at: AwareDatetime | None = None
    last_seen_at: AwareDatetime | None = None
    expires_at: AwareDatetime | None = None
    current: bool | None = None


class User(BaseModel):
    id: UUID
    username: str
    email: EmailStr
    display_name: str | None = None
    roles: list[RoleName]
    status: UserStatus
    mfa_enabled: bool | None = None
    mfa_required: bool | None = None
    last_login_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class UserWithInvite(User):
    invite_url: str | None = Field(None, description='One-time link, valid 72 h. Shown once.')
    invite_expires_at: AwareDatetime | None = None


class UpdateUserRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    display_name: str | None = Field(None, max_length=80)
    status: UserStatus | None = None
    roles: list[RoleName] | None = Field(None, min_length=1)
    mfa_required: bool | None = None


class Role(BaseModel):
    id: UUID | None = None
    name: RoleName | None = None
    description: str | None = None
    permissions: list[str] | None = None
    user_count: int | None = None


class Level(StrEnum):
    """
    `trade` implies `read`.
    """

    read = 'read'
    trade = 'trade'


class AccountAccessGrantInput(BaseModel):
    exchange_account_id: UUID
    level: Level = Field(..., description='`trade` implies `read`.')


class AccountAccessGrant(AccountAccessGrantInput):
    account_label: str | None = None
    environment: Environment | None = None
    granted_at: AwareDatetime | None = None
    granted_by: UUID | None = None


class ConnectionState(StrEnum):
    pending = 'pending'
    connected = 'connected'
    degraded = 'degraded'
    disconnected = 'disconnected'
    disabled = 'disabled'


class KeyStatus1(StrEnum):
    missing = 'missing'
    pending = 'pending'
    active = 'active'
    rotating = 'rotating'
    expired = 'expired'
    invalid = 'invalid'


class WalletBalance(BaseModel):
    is_paper: bool | None = Field(
        False,
        description='True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).',
    )
    coin: str | None = Field(None, examples=['USDT'])
    equity: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    wallet_balance: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    available_balance: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unrealised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    account_im_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    account_mm_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    updated_at: AwareDatetime | None = None


class CreateExchangeAccountRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exchange: ExchangeCode
    environment: Environment
    kind: AccountKind
    label: str = Field(..., max_length=80, min_length=1)
    exchange_uid: str = Field(..., pattern='^[0-9]{4,20}$')
    parent_account_id: UUID | None = Field(None, description='Required when `kind=sub`.')


class UpdateExchangeAccountRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    label: str | None = Field(None, max_length=80)
    enabled: bool | None = None
    active_profile_id: UUID | None = None
    position_mode: PositionMode | None = None
    margin_mode: MarginMode | None = None


class ApiKey(BaseModel):
    id: UUID
    exchange_account_id: UUID
    key_id_masked: str = Field(..., description='First and last 4 characters only.')
    label: str | None = Field(None, max_length=80)
    status: KeyStatus
    read_only: bool | None = None
    expires_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    last_verified_at: AwareDatetime | None = None


class CreateApiKeyRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    api_key: SecretStr = Field(..., max_length=128, min_length=8)
    api_secret: SecretStr = Field(..., max_length=256, min_length=8)
    label: str | None = Field(None, max_length=80)
    read_only: bool | None = False
    expected_uid: str | None = Field(
        None, description="Must equal the account's `exchange_uid`; mismatch is rejected."
    )


class KeyVerification(BaseModel):
    passed: bool
    uid: str | None = None
    unified: bool | None = None
    permissions: dict[str, list[str]] | None = None
    withdraw_enabled: bool = Field(..., description='Must be false; a true value causes rejection.')
    ip_whitelist: list[str] | None = None
    ip_whitelist_matches_egress: bool | None = None
    clock_offset_ms: int | None = None
    probe_ret_code: int | None = None
    warnings: list[str] | None = None


class ApiKeyWithVerification(BaseModel):
    key: ApiKey | None = None
    verification: KeyVerification | None = None


class RotateApiKeyRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    api_key: SecretStr
    api_secret: SecretStr
    label: str | None = Field(None, max_length=80)
    overlap_seconds: int | None = Field(300, ge=0, le=3600)


class State(StrEnum):
    overlapping = 'overlapping'
    completed = 'completed'
    failed = 'failed'


class ApiKeyRotation(BaseModel):
    rotation_id: UUID | None = None
    old_key_id: UUID | None = None
    new_key: ApiKey | None = None
    verification: KeyVerification | None = None
    overlap_until: AwareDatetime | None = None
    state: State | None = None


class Rest(BaseModel):
    ok: bool | None = None
    latency_ms: int | None = None
    ret_code: int | None = None
    error: str | None = None


class Websocket(BaseModel):
    ok: bool | None = None
    latency_ms: int | None = None
    error: str | None = None


class KeyTestResult(BaseModel):
    passed: bool | None = None
    checked_at: AwareDatetime | None = None
    rest: Rest | None = None
    websocket: Websocket | None = None
    verification: KeyVerification | None = None


class Offset(BaseModel):
    """
    A distance expressed in one of several units; resolved server-side to a price.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    unit: OffsetUnit
    value: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    atr_period: int | None = Field(14, description='Used when `unit=atr`.', ge=2, le=200)
    atr_bar_type: BarType | None = None
    atr_param: str | None = Field(None, max_length=24)


class Sizing(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    mode: SizingMode
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    pct: str | None = Field(
        None,
        description='Percent of equity (`pct_equity`) or of the position (`pct_position`).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    risk_per_trade_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    risk_per_trade_pct: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    round_to_lot: bool | None = True


class RiskCaps(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    max_daily_loss_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_daily_loss_pct: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_open_positions: int | None = Field(None, ge=0, le=100)
    max_position_notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_orders_per_minute: int | None = Field(None, ge=1, le=600)
    max_consecutive_losses: int | None = Field(None, ge=1, le=50)
    lockout_minutes_after_breach: int | None = Field(60, ge=0, le=1440)


class AccountProfileInput(BaseModel):
    name: str = Field(..., max_length=80, min_length=1)
    leverage: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    sizing: Sizing
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    risk_caps: RiskCaps | None = None
    allowed_symbols: list[Symbol] | None = Field(
        None, description='Empty means "all instruments permitted by the deployment".'
    )
    require_native_stop: Literal[True] = Field(
        True, description='Always true; the safety invariant cannot be disabled (arch P4).'
    )
    default_time_in_force: TimeInForce | None = None
    default_tpsl_mode: TpSlMode | None = None


class AccountProfile(AccountProfileInput):
    id: UUID | None = None
    exchange_account_id: UUID | None = None
    is_active: bool | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Status(StrEnum):
    Trading = 'Trading'
    PreLaunch = 'PreLaunch'
    Delivering = 'Delivering'
    Closed = 'Closed'


class Instrument(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    category: Literal['linear']
    base_coin: str | None = None
    quote_coin: str | None = None
    settle_coin: str | None = None
    contract_type: str | None = Field(None, examples=['LinearPerpetual'])
    status: Status | None = None
    tick_size: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_scale: int | None = None
    qty_step: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    min_order_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_order_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    min_notional_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_leverage: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    leverage_step: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    funding_interval_minutes: int | None = None
    launch_time: AwareDatetime | None = None
    copy_trading: bool | None = None
    revision: int | None = Field(
        None, description='Increments whenever Bybit changes the instrument metadata.'
    )
    updated_at: AwareDatetime | None = None


class RiskLimitTier(BaseModel):
    tier: int | None = None
    risk_limit_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    initial_margin: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    maintenance_margin: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_leverage: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class InstrumentDetail(Instrument):
    risk_limit_tiers: list[RiskLimitTier] | None = None
    recorded: bool | None = None
    recording_started_at: AwareDatetime | None = None


class Ticker(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    last_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    mark_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    index_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bid1_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bid1_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ask1_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ask1_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_change_pct_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    high_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    low_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    volume_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    turnover_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_interest: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_interest_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    funding_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    next_funding_time: AwareDatetime | None = None
    ts: AwareDatetime | None = None
    stale: bool | None = None


class Bar(BaseModel):
    t: AwareDatetime = Field(..., description='Bar open time.')
    close_time: AwareDatetime | None = Field(None, description='Present for non-time bars.')
    o: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    h: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    l: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    c: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    v: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    turnover: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    trades: int | None = None
    confirm: bool | None = Field(
        None, description='False for the in-progress bar (Bybit `confirm` semantics).'
    )
    delta: Decimal | None = None
    cvd: Decimal | None = None
    min_delta: Decimal | None = None
    max_delta: Decimal | None = None


class KlineResponse(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    interval: str | None = None
    bar_type: BarType | None = None
    bars: list[Bar]
    meta: DataMeta


class FootprintCell(BaseModel):
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    bid_volume: str = Field(
        ...,
        description='Volume traded into the bid (taker sells).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ask_volume: str = Field(
        ...,
        description='Volume traded into the ask (taker buys).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    total_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    trades: int | None = None


class Direction(StrEnum):
    buy = 'buy'
    sell = 'sell'


class FootprintImbalance(BaseModel):
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    direction: Direction | None = None
    ratio: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    stacked: bool | None = None
    stack_size: int | None = None
    estimated: bool | None = False


class UnfinishedAuction(BaseModel):
    high: bool | None = None
    low: bool | None = None


class FootprintBar(Bar):
    poc_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_high: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_low: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unfinished_auction: UnfinishedAuction | None = None
    cells: list[FootprintCell] | None = None
    imbalances: list[FootprintImbalance] | None = None


class FootprintResponse(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    bar_type: BarType | None = None
    param: str | None = None
    tick_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_grouping: int | None = None
    bars: list[FootprintBar]
    meta: DataMeta


class ProfileRow(BaseModel):
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    buy_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    sell_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    delta: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tpo_count: int | None = None


class ProfilePeriod(BaseModel):
    period_start: AwareDatetime | None = None
    period_end: AwareDatetime | None = None
    total_volume: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    poc_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_high: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    value_area_low: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    naked_poc: bool | None = Field(
        None, description="True while this period's POC has not been retraded by a later bar."
    )
    rows: list[ProfileRow] | None = None
    hvn: list[Decimal] | None = None
    lvn: list[Decimal] | None = None


class Kind(StrEnum):
    volume = 'volume'
    delta = 'delta'
    tpo = 'tpo'


class Split(StrEnum):
    composite = 'composite'
    session = 'session'
    fixed = 'fixed'


class ProfileResponse(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    kind: Kind | None = None
    split: Split | None = None
    profiles: list[ProfilePeriod] | None = None
    meta: DataMeta | None = None


class Side(StrEnum):
    """
    Taker/aggressor side, taken directly from Bybit `S`.
    """

    buy = 'buy'
    sell = 'sell'


class TickDirection(StrEnum):
    PlusTick = 'PlusTick'
    ZeroPlusTick = 'ZeroPlusTick'
    MinusTick = 'MinusTick'
    ZeroMinusTick = 'ZeroMinusTick'


class PublicTrade(BaseModel):
    id: str | None = None
    ts: AwareDatetime | None = None
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    side: Side | None = Field(
        None, description='Taker/aggressor side, taken directly from Bybit `S`.'
    )
    is_block_trade: bool | None = None
    cluster_size: int | None = Field(
        None, description='Number of raw prints merged when clustering is on.'
    )
    tick_direction: TickDirection | None = None


class Depth(IntEnum):
    integer_1 = 1
    integer_50 = 50
    integer_200 = 200
    integer_500 = 500


class Bid(RootModel[list[Decimal]]):
    root: list[Decimal] = Field(..., max_length=2, min_length=2)


class Ask(RootModel[list[Decimal]]):
    root: list[Decimal] = Field(..., max_length=2, min_length=2)


class OrderbookSnapshot(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    depth: Depth
    u: int = Field(..., description='Monotonic update id from Bybit.')
    seq: int = Field(..., description='Cross-topic sequence from Bybit.')
    ts: AwareDatetime
    bids: list[Bid] = Field(..., description='[price, size], descending.')
    asks: list[Ask] = Field(..., description='[price, size], ascending.')
    stale: bool | None = None


class Normalize(StrEnum):
    none = 'none'
    column = 'column'
    window = 'window'


class HeatmapResponse(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    from_: AwareDatetime | None = Field(None, alias='from')
    to: AwareDatetime | None = None
    time_bucket_ms: int | None = None
    price_grouping: int | None = None
    times: list[AwareDatetime] | None = None
    prices: list[Decimal] | None = None
    bid_matrix: list[list[float]] | None = Field(
        None, description='Row-major [price][time] resting bid size.'
    )
    ask_matrix: list[list[float]] | None = Field(
        None, description='Row-major [price][time] resting ask size.'
    )
    max_value: float | None = None
    normalize: Normalize | None = None
    estimated: bool | None = False


class MetricPoint(BaseModel):
    t: AwareDatetime
    v: Decimal | None
    meta: dict[str, Any] | None = Field(
        None, description='Per-point detail for event-like metrics (iceberg, stop_run, absorption).'
    )


class MetricSeries(BaseModel):
    metric: MetricCode
    estimated: bool | None = Field(None, description='True for heuristic metrics (arch P10).')
    params: dict[str, Any] | None = None
    unit: str | None = Field(
        None, examples=['base_volume', 'index', 'ratio', 'confidence', 'usd', 'price']
    )
    points: list[MetricPoint]


class MetricsResponse(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    bar_type: BarType | None = None
    param: str | None = None
    series: list[MetricSeries] | None = None
    meta: DataMeta | None = None


class Side1(StrEnum):
    buy = 'buy'
    sell = 'sell'


class Liquidation(BaseModel):
    ts: AwareDatetime | None = None
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: Side1 | None = None
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cluster_size: int | None = None


class Tier(StrEnum):
    questdb = 'questdb'
    parquet = 'parquet'


class Interval(BaseModel):
    from_: AwareDatetime | None = Field(None, alias='from')
    to: AwareDatetime | None = None
    tier: Tier | None = None
    rows: int | None = None


class Reason(StrEnum):
    ws_disconnect = 'ws_disconnect'
    backend_restart = 'backend_restart'
    retention_purge = 'retention_purge'
    never_recorded = 'never_recorded'
    exchange_outage = 'exchange_outage'


class Gap(BaseModel):
    from_: AwareDatetime | None = Field(None, alias='from')
    to: AwareDatetime | None = None
    reason: Reason | None = None


class Stream(BaseModel):
    stream: StreamKind | None = None
    intervals: list[Interval] | None = None
    gaps: list[Gap] | None = None


class DataCoverage(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    streams: list[Stream] | None = None
    generated_at: AwareDatetime | None = None


class RecordedSymbol(BaseModel):
    id: UUID
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    reason: RecordReason
    pinned: bool | None = None
    state: RecordingState
    streams: list[StreamKind] | None = None
    depth: Depth | None = None
    started_at: AwareDatetime | None = None
    retention_days: int | None = None
    disk_bytes: int | None = None
    rows_last_hour: int | None = None
    lag_ms: int | None = None
    added_by: UUID | None = None


class Estimate(BaseModel):
    """
    Planning estimate, replaced by measured rates once the recorder has run for an hour.
    """

    daily_bytes_estimate: int | None = None
    basis: str | None = Field(None, examples=['~0.5-0.75 GB/day/symbol compressed at depth 200'])
    warning: str | None = None


class RecordedSymbolWithEstimate(RecordedSymbol):
    estimate: Estimate | None = Field(
        None,
        description='Planning estimate, replaced by measured rates once the recorder has run for an hour.',
    )


class AddRecordedSymbolRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    streams: list[StreamKind] | None = Field(
        ['trades', 'orderbook_delta', 'tickers', 'liquidations'], min_length=1
    )
    depth: Depth | None = 200
    pinned: bool | None = False
    retention_days: int | None = Field(30, ge=1, le=3650)


class UpdateRecordedSymbolRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    streams: list[StreamKind] | None = Field(None, min_length=1)
    depth: Depth | None = None
    pinned: bool | None = None
    retention_days: int | None = Field(None, ge=1, le=3650)


class State1(StrEnum):
    connecting = 'connecting'
    connected = 'connected'
    degraded = 'degraded'
    disconnected = 'disconnected'


class Connection(BaseModel):
    endpoint: str | None = None
    state: State1 | None = None
    subscribed_topics: int | None = None
    connected_since: AwareDatetime | None = None
    reconnects_last_hour: int | None = None
    last_ping_ms: int | None = None


class Symbol1(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    state: RecordingState | None = None
    lag_ms: int | None = None
    rows_last_hour: int | None = None
    dropped_messages: int | None = None
    resyncs_last_hour: int | None = None
    last_event_at: AwareDatetime | None = None


class RecordingStatus(BaseModel):
    overall: ComponentState | None = None
    connections: list[Connection] | None = None
    symbols: list[Symbol1] | None = None
    ingest_rate_msgs_per_sec: int | None = None
    write_backlog_rows: int | None = None
    generated_at: AwareDatetime | None = None


class Tier2(StrEnum):
    questdb = 'questdb'
    parquet = 'parquet'
    postgres = 'postgres'


class Tier1(BaseModel):
    tier: Tier2 | None = None
    used_bytes: int | None = None
    retention_days: int | None = None


class Symbol2(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    used_bytes: int | None = None
    daily_growth_bytes: int | None = None
    pinned: bool | None = None


class StorageUsage(BaseModel):
    disk_total_bytes: int | None = None
    disk_used_bytes: int | None = None
    disk_free_bytes: int | None = None
    projected_full_at: AwareDatetime | None = None
    daily_growth_bytes: int | None = None
    tiers: list[Tier1] | None = None
    symbols: list[Symbol2] | None = None
    generated_at: AwareDatetime | None = None


class RetentionPolicyInput(BaseModel):
    stream: StreamKind
    retain_days: int = Field(..., ge=1, le=3650)
    action: RetentionAction
    symbol: Symbol | None = Field(None, description='Null = global default.')
    applies_to_pinned: bool | None = False


class RetentionPolicy(RetentionPolicyInput):
    id: UUID | None = None
    updated_at: AwareDatetime | None = None


class RecordingSession(BaseModel):
    id: UUID | None = None
    recorded_symbol_id: UUID | None = None
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    state: RecordingState | None = None
    started_at: AwareDatetime | None = None
    ended_at: AwareDatetime | None = None
    streams: list[StreamKind] | None = None
    depth: int | None = None
    rows: int | None = None
    bytes: int | None = None
    gap_count: int | None = None


class CreateReplaySessionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbols: list[Symbol] = Field(..., max_length=8, min_length=1)
    from_: AwareDatetime = Field(..., alias='from')
    to: AwareDatetime
    speed: float | None = Field(
        1, description='0 = as fast as possible (used by rule simulation).', ge=0.0, le=100.0
    )
    streams: list[StreamKind] | None = None
    depth: Depth | None = 200
    paper_account_id: UUID | None = None
    autostart: bool | None = False


class ReplaySession(BaseModel):
    id: UUID | None = None
    state: ReplayState | None = None
    symbols: list[Symbol] | None = None
    from_: AwareDatetime | None = Field(None, alias='from')
    to: AwareDatetime | None = None
    cursor_ts: AwareDatetime | None = None
    speed: float | None = None
    streams: list[StreamKind] | None = None
    depth: int | None = None
    paper_account_id: UUID | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    progress_pct: float | None = Field(None, ge=0.0, le=100.0)
    error: str | None = None


class Action(StrEnum):
    play = 'play'
    pause = 'pause'
    seek = 'seek'
    step = 'step'
    set_speed = 'set_speed'
    restart = 'restart'


class ReplayControlRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    action: Action
    speed: float | None = Field(None, ge=0.0, le=100.0)
    to: AwareDatetime | None = Field(None, description='Required for `seek`.')
    step_events: int | None = Field(None, ge=1, le=100000)
    step_ms: int | None = Field(None, ge=1, le=3600000)


class Direction1(StrEnum):
    rise = 'rise'
    fall = 'fall'


class TriggerSpec(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    price: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    trigger_by: TriggerBy | None = None
    direction: Direction1


class Oco(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    other_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    other_trigger: TriggerSpec | None = None
    cancel_timeout_ms: int | None = Field(
        2000,
        description="Max time to cancel the loser after the winner's fill notice arrives on the WS.",
        ge=100,
        le=60000,
    )


class Iceberg(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    display_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    refresh_on_fill_pct: float | None = Field(100, ge=1.0, le=100.0)
    randomize_display_pct: float | None = Field(0, ge=0.0, le=50.0)


class Twap(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    duration_seconds: int | None = Field(None, ge=10, le=86400)
    slices: int | None = Field(None, ge=2, le=500)
    randomize_pct: float | None = Field(0, ge=0.0, le=50.0)
    limit_offset_ticks: int | None = Field(
        None, description='Omit for market slices.', ge=0, le=1000
    )


class Chase(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    offset_ticks: int | None = Field(0, ge=0, le=100)
    max_chases: int | None = Field(20, ge=1, le=500)
    max_slippage_ticks: int | None = Field(None, ge=1, le=10000)
    repricing_interval_ms: int | None = Field(250, ge=50, le=10000)
    fallback_to_market: bool | None = False


class Distribution(StrEnum):
    equal = 'equal'
    linear = 'linear'
    geometric = 'geometric'


class Scaled(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    levels: int | None = Field(None, ge=2, le=50)
    from_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    to_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    distribution: Distribution | None = None
    skew: str | None = Field(
        None,
        description='>1 weights size toward `to_price`.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class TakeProfitLevel(BaseModel):
    offset: Offset | None = None
    pct_of_position: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Bracket(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    take_profit_levels: list[TakeProfitLevel] | None = Field(None, max_length=10)
    move_stop_to_breakeven_at: Offset | None = None


class AlgoSpec(BaseModel):
    """
    Emulated execution algorithms. None of these exist as native Bybit order types on
    `/v5/order/create`; all are implemented client-of-exchange-side by the OMS (digest 09).

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    kind: AlgoKind
    oco: Oco | None = None
    iceberg: Iceberg | None = None
    twap: Twap | None = None
    chase: Chase | None = None
    scaled: Scaled | None = None
    bracket: Bracket | None = None


class PositionIdx(IntEnum):
    """
    Required in hedge mode (1 = long, 2 = short).
    """

    integer_0 = 0
    integer_1 = 1
    integer_2 = 2


class PlaceOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exchange_account_id: UUID
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: OrderSide
    order_type: OrderType
    intent: OrderIntent | None = 'entry'
    sizing: Sizing
    price: str | None = Field(
        None,
        description='Required for `limit`.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    time_in_force: TimeInForce | None = None
    reduce_only: bool | None = False
    close_on_trigger: bool | None = False
    position_idx: PositionIdx | None = Field(
        None, description='Required in hedge mode (1 = long, 2 = short).'
    )
    trigger: TriggerSpec | None = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    tpsl_mode: TpSlMode | None = None
    algo: AlgoSpec | None = None
    profile_id: UUID | None = Field(
        None, description="Override the account's active profile for this order."
    )
    arm_token: str | None = Field(
        None, description='Required when the request originates from one-click/hotkey entry.'
    )
    note: str | None = Field(None, max_length=280)


class AmendOrderRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    trigger_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    take_profit: Offset | None = None
    stop_loss: Offset | None = None


class CancelAllRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exchange_account_ids: list[UUID] | None = Field(
        None, description='Empty = every account in scope.'
    )
    symbol: Symbol | None = None
    intents: list[OrderIntent] | None = None
    exclude_reduce_only: bool | None = Field(
        True, description='Protects TP/SL exits from a blanket cancel.'
    )


class TriggerDirection(Enum):
    rise = 'rise'
    fall = 'fall'
    NoneType_None = None


class Order(BaseModel):
    is_paper: bool | None = Field(
        False,
        description='True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).',
    )
    id: UUID
    exchange_account_id: UUID
    trade_group_id: UUID | None = None
    trade_group_leg_id: UUID | None = None
    parent_order_id: UUID | None = None
    order_link_id: str | None = Field(
        None, description='Deterministic, derived from the Idempotency-Key.', max_length=36
    )
    exchange_order_id: str | None = None
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: OrderSide
    order_type: OrderType
    intent: OrderIntent | None = None
    state: OrderState
    qty: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    filled_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    remaining_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price: Decimal | None = None
    avg_fill_price: Decimal | None = None
    time_in_force: TimeInForce | None = None
    reduce_only: bool | None = None
    close_on_trigger: bool | None = None
    position_idx: int | None = None
    trigger_price: Decimal | None = None
    trigger_by: TriggerBy | None = None
    trigger_direction: TriggerDirection | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    tpsl_mode: TpSlMode | None = None
    algo: AlgoSpec | None = None
    environment: Environment | None = None
    rejected_reason: str | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class OrderEventKind(StrEnum):
    """
    Append-only OMS event taxonomy. Exact 1:1 mirror of the Postgres type
    `order_event_kind` (`21-database-schema.md`, table `order_events`) — no supersets,
    no omissions; contract test `enum_parity_order_event_kind` asserts set equality.

    """

    local_create = 'local_create'
    submit_attempt = 'submit_attempt'
    ack = 'ack'
    reject = 'reject'
    fill = 'fill'
    partial_fill = 'partial_fill'
    amend_request = 'amend_request'
    amend_ack = 'amend_ack'
    cancel_request = 'cancel_request'
    cancel_ack = 'cancel_ack'
    expire = 'expire'
    exchange_push = 'exchange_push'
    reconcile_diff = 'reconcile_diff'
    error = 'error'


class OrderEvent(BaseModel):
    id: int | None = None
    kind: OrderEventKind | None = None
    event_ts: AwareDatetime | None = None
    payload: dict[str, Any] | None = None


class PositionIdx1(IntEnum):
    integer_0 = 0
    integer_1 = 1
    integer_2 = 2


class Overrides(BaseModel):
    """
    Per-leg overrides layered on top of the account profile and request defaults.
    """

    model_config = ConfigDict(
        extra='forbid',
    )
    profile_id: UUID | None = None
    sizing: Sizing | None = None
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    leverage: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    time_in_force: TimeInForce | None = None
    tpsl_mode: TpSlMode | None = None
    position_idx: PositionIdx1 | None = None
    skip: bool | None = Field(
        False, description='Keep the leg in the group for auditability but do not send it.'
    )


class TradeGroupLegInput(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exchange_account_id: UUID
    overrides: Overrides | None = Field(
        None,
        description='Per-leg overrides layered on top of the account profile and request defaults.',
    )


class Atomicity(StrEnum):
    best_effort = 'best_effort'
    all_or_none = 'all_or_none'


class Compensate(StrEnum):
    """
    Applies when `all_or_none` fails after sending.
    """

    none = 'none'
    flatten_filled = 'flatten_filled'


class Defaults(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    sizing: Sizing | None = None
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    time_in_force: TimeInForce | None = None
    trigger: TriggerSpec | None = None
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    tpsl_mode: TpSlMode | None = None


class CreateTradeGroupRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: OrderSide
    order_type: OrderType
    intent: OrderIntent | None = 'entry'
    reduce_only: bool | None = False
    atomicity: Atomicity | None = 'best_effort'
    compensate: Compensate | None = Field(
        'none', description='Applies when `all_or_none` fails after sending.'
    )
    max_concurrent_legs: int | None = Field(5, ge=1, le=20)
    defaults: Defaults | None = None
    algo: AlgoSpec | None = None
    legs: list[TradeGroupLegInput] = Field(..., max_length=25, min_length=1)
    arm_token: str | None = None
    note: str | None = Field(None, max_length=280)
    rule_id: UUID | None = Field(
        None, description='Set when the group originates from the rule engine.'
    )


class ResolvedLegParams(BaseModel):
    """
    The exact parameters the server computed for a leg, echoed for pre-trade transparency. `leverage`, `stop_loss_price` and `take_profit_price` persist to the `resolved_leverage`, `resolved_sl_price` and `resolved_tp_price` columns on `trade_group_legs`; the remaining fields are the derivation shown to the user and are captured in the leg's `profile_snapshot` JSONB so a historical fan-out can be explained even after the profile is edited.

    """

    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price: Decimal | None = None
    leverage: str | None = Field(
        None,
        description='Persisted as `resolved_leverage`.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    stop_loss_price: str | None = Field(
        None,
        description='Persisted as `resolved_sl_price`. Never null - the native-stop invariant.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    take_profit_price: Decimal | None = Field(None, description='Persisted as `resolved_tp_price`.')
    trailing_stop_distance: Decimal | None = None
    notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    risk_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    estimated_fee_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    sizing_explanation: str | None = Field(
        None,
        description='Human-readable derivation, shown in the ticket\'s "why this size" tooltip.',
    )


class LegError(BaseModel):
    """
    Serialised form of the `rejection_code` / `rejection_message` columns on `trade_group_legs`.

    """

    code: str | None = Field(
        None, description='One of the `x-error-codes` slugs; persisted as `rejection_code`.'
    )
    message: str | None = Field(None, description='Persisted as `rejection_message`.')
    exchange_ret_code: int | None = None
    retryable: bool | None = None


class Totals(BaseModel):
    requested_legs: int | None = None
    submitted_legs: int | None = None
    rejected_legs: int | None = None
    filled_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    target_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl: Decimal | None = None


class Leg(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    leg_id: UUID
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    stop_loss: Offset | None = None
    take_profit: Offset | None = None


class AmendTradeGroupRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    stop_loss: Offset | None = None
    take_profit: Offset | None = None
    trailing_stop: Offset | None = None
    legs: list[Leg] | None = Field(
        None,
        description='Per-leg amendments; when present, the top-level fields are ignored for those legs.',
    )


class Result(BaseModel):
    exchange_account_id: UUID | None = None
    ok: bool | None = None
    affected: int | None = None
    error: LegError | None = None


class BulkAccountResult(BaseModel):
    results: list[Result] | None = None
    requested: int | None = None
    succeeded: int | None = None


class Result1(BaseModel):
    leg_id: UUID | None = None
    exchange_account_id: UUID | None = None
    ok: bool | None = None
    affected: int | None = None
    error: LegError | None = None


class BulkLegResult(BaseModel):
    trade_group_id: UUID | None = None
    results: list[Result1] | None = None
    requested: int | None = None
    succeeded: int | None = None


class Scope(StrEnum):
    global_ = 'global'
    accounts = 'accounts'


class KillSwitch(BaseModel):
    engaged: bool
    scope: Scope
    exchange_account_ids: list[UUID] | None = None
    engaged_at: AwareDatetime | None = None
    engaged_by: UUID | None = None
    reason: str | None = None


class SetKillSwitchRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    engaged: bool
    scope: Scope
    exchange_account_ids: list[UUID] | None = None
    cancel_open_orders: bool | None = True
    flatten_positions: bool | None = False
    disarm_rules: bool | None = True
    reason: str = Field(..., max_length=280, min_length=3)


class Actions(BaseModel):
    orders_cancelled: int | None = None
    positions_flattened: int | None = None
    rules_disarmed: int | None = None
    failures: list[dict[str, Any]] | None = None


class KillSwitchResult(BaseModel):
    state: KillSwitch | None = None
    actions: Actions | None = None


class Side2(StrEnum):
    long = 'long'
    short = 'short'
    flat = 'flat'


class Position(BaseModel):
    is_paper: bool | None = Field(
        False,
        description='True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).',
    )
    id: UUID
    exchange_account_id: UUID
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: Side2
    position_idx: PositionIdx1 | None = None
    size: str = Field(
        ...,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    mark_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    position_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    leverage: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    margin_mode: MarginMode | None = None
    unrealised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl_session: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    liq_price: Decimal | None = None
    bust_price: Decimal | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop: str | None = Field(
        None,
        description='Price distance, not a percentage (Bybit semantics).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tpsl_mode: TpSlMode | None = None
    native_stop_present: bool | None = Field(
        None,
        description='False is an alarm condition; the OMS re-asserts the stop and raises a critical alert.',
    )
    trade_group_id: UUID | None = None
    r_multiple: Decimal | None = None
    updated_at: AwareDatetime | None = None


class Side3(StrEnum):
    long = 'long'
    short = 'short'


class Account(BaseModel):
    exchange_account_id: UUID | None = None
    size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    side: Side3 | None = None
    unrealised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class AggregatePosition(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    net_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    gross_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    weighted_avg_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unrealised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    accounts: list[Account] | None = None


class SetTpSlRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    take_profit: Offset | None = None
    stop_loss: Offset | None = None
    trailing_stop: Offset | None = None
    activation_price: str | None = Field(
        None,
        description='Arms the trailing stop only once price reaches this level.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tpsl_mode: TpSlMode | None = None
    tp_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    sl_size: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tp_trigger_by: TriggerBy | None = None
    sl_trigger_by: TriggerBy | None = None


class TpSlResult(BaseModel):
    position_id: UUID | None = None
    take_profit: Decimal | None = None
    stop_loss: Decimal | None = None
    trailing_stop_distance: Decimal | None = None
    trailing_stop_requested: Offset | None = None
    activation_price: Decimal | None = None
    tpsl_mode: TpSlMode | None = None
    applied_at: AwareDatetime | None = None


class ClosePositionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    order_type: OrderType
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    pct: str | None = Field(
        None,
        description='0 < pct <= 100. Mutually exclusive with `qty`.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    time_in_force: TimeInForce | None = None
    arm_token: str | None = None


class SizeMode(StrEnum):
    same = 'same'
    profile = 'profile'
    custom = 'custom'


class ReversePositionRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    size_mode: SizeMode | None = 'same'
    qty: str | None = Field(
        None,
        description='Required when `size_mode=custom`.',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    order_type: OrderType | None = 'market'
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    arm_token: str | None = None


class ExecType(StrEnum):
    Trade = 'Trade'
    AdlTrade = 'AdlTrade'
    Funding = 'Funding'
    BustTrade = 'BustTrade'
    Settle = 'Settle'


class Execution(BaseModel):
    is_paper: bool | None = Field(
        False,
        description='True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).',
    )
    id: UUID | None = None
    exec_id: str | None = None
    order_id: UUID | None = None
    exchange_account_id: UUID | None = None
    trade_group_id: UUID | None = None
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: OrderSide | None = None
    exec_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    exec_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    exec_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fee: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fee_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fee_coin: str | None = None
    is_maker: bool | None = None
    exec_type: ExecType | None = None
    exec_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    ts: AwareDatetime | None = None


class ClosedPnl(BaseModel):
    id: UUID | None = None
    exchange_account_id: UUID | None = None
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: JournalSide | None = None
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_entry_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_exit_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    closed_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cum_entry_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cum_exit_value: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    leverage: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None


class RuleOperand1(BaseModel):
    """
    A value position in the condition tree. Exactly one form is present:
    a metric reference, a constant, or an arithmetic node.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    const: str | float | bool


class RuleMetricRef(BaseModel):
    """
    Reference to a value in the metric registry (24-internal-schemas.md section 7.2). `symbol` and `account_id` default to the rule's scope when null.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    metric: str = Field(..., pattern='^[a-z][a-z0-9_]{1,48}$')
    params: dict[str, Any] | None = None
    symbol: Symbol | None = None
    account_id: UUID | None = None
    timeframe: str | None = None


class Op(StrEnum):
    add = 'add'
    sub = 'sub'
    mul = 'mul'
    div = 'div'
    abs = 'abs'
    min = 'min'
    max = 'max'
    neg = 'neg'
    pct_of = 'pct_of'


class Op1(StrEnum):
    gt = 'gt'
    gte = 'gte'
    lt = 'lt'
    lte = 'lte'
    eq = 'eq'
    neq = 'neq'
    between = 'between'
    outside = 'outside'
    crosses_above = 'crosses_above'
    crosses_below = 'crosses_below'
    changed = 'changed'
    is_true = 'is_true'
    is_false = 'is_false'
    in_set = 'in_set'
    not_in_set = 'not_in_set'


class Op2(StrEnum):
    all_of = 'all_of'
    any_of = 'any_of'
    none_of = 'none_of'
    n_of = 'n_of'


class Op3(StrEnum):
    sustained_for = 'sustained_for'
    occurred_within = 'occurred_within'
    count_within = 'count_within'
    stable_for = 'stable_for'


class Type(StrEnum):
    """
    Order-sending actions (`place_order`, `flatten_*`, `reverse_position`,
    `scale_in`, `scale_out`, `modify_*`, `cancel_*`, `reduce_leverage`,
    `arm_chase_limit`, `start_*`) require the rule to be `armed` and the author to
    hold `orders:write` on every bound account. `widen_stop` additionally requires
    an owner with an elevated session - it is the only action that can increase
    risk, so it is gated separately from the rest.

    """

    place_order = 'place_order'
    modify_stop_loss = 'modify_stop_loss'
    modify_take_profit = 'modify_take_profit'
    cancel_order = 'cancel_order'
    cancel_all_orders = 'cancel_all_orders'
    move_to_breakeven = 'move_to_breakeven'
    scale_out = 'scale_out'
    scale_in = 'scale_in'
    flatten_position = 'flatten_position'
    flatten_all_positions = 'flatten_all_positions'
    reverse_position = 'reverse_position'
    halt_new_orders = 'halt_new_orders'
    resume_new_orders = 'resume_new_orders'
    reduce_leverage = 'reduce_leverage'
    widen_stop = 'widen_stop'
    tighten_stop = 'tighten_stop'
    arm_chase_limit = 'arm_chase_limit'
    start_iceberg_slice = 'start_iceberg_slice'
    start_twap = 'start_twap'
    send_notification = 'send_notification'
    log_journal_tag = 'log_journal_tag'
    set_variable = 'set_variable'
    emit_signal = 'emit_signal'
    pause_rule = 'pause_rule'
    enable_rule = 'enable_rule'


class OnError(StrEnum):
    abort_remaining = 'abort_remaining'
    continue_ = 'continue'
    retry_once = 'retry_once'


class Targets(StrEnum):
    scope_accounts = 'scope_accounts'
    originating_account = 'originating_account'
    all_accounts = 'all_accounts'


class RuleAction(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    node_id: str
    type: Type = Field(
        ...,
        description='Order-sending actions (`place_order`, `flatten_*`, `reverse_position`,\n`scale_in`, `scale_out`, `modify_*`, `cancel_*`, `reduce_leverage`,\n`arm_chase_limit`, `start_*`) require the rule to be `armed` and the author to\nhold `orders:write` on every bound account. `widen_stop` additionally requires\nan owner with an elevated session - it is the only action that can increase\nrisk, so it is gated separately from the rest.\n',
    )
    params: dict[str, Any] = Field(..., description='Validated against a per-action JSON Schema.')
    on_error: OnError | None = 'abort_remaining'
    targets: Targets | None = 'scope_accounts'
    dry_run_only: bool | None = False


class OncePer(Enum):
    position = 'position'
    day = 'day'
    group = 'group'
    rule_lifetime = 'rule_lifetime'
    NoneType_None = None


class RuleLimits(BaseModel):
    """
    Safety limiters applied by the engine before any action is dispatched. Named `limits` in the IR (not `guards`) to match 24-internal-schemas.md section 11.2.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    once: bool | None = False
    once_per: OncePer | None = None
    cooldown_ms: int | None = Field(1000, ge=0)
    max_fires_per_hour: int | None = Field(60, ge=1)
    max_fires_per_day: int | None = Field(500, ge=1)
    max_actions_per_fire: int | None = Field(10, ge=1, le=10)
    max_notional_per_fire: Decimal | None = None
    max_daily_notional: Decimal | None = None
    require_confirmation: bool | None = False
    evaluation_timeout_ms: int | None = Field(250, ge=10, le=5000)
    kill_switch_on_error_count: int | None = Field(5, ge=1)


class Type1(StrEnum):
    on_price_update = 'on_price_update'
    on_bar_close = 'on_bar_close'
    on_order_fill = 'on_order_fill'
    on_position_open = 'on_position_open'
    on_position_close = 'on_position_close'
    on_position_update = 'on_position_update'
    on_timer = 'on_timer'
    on_metric_change = 'on_metric_change'
    on_signal = 'on_signal'
    on_schedule = 'on_schedule'
    pre_trade_check = 'pre_trade_check'
    on_book_update = 'on_book_update'
    on_liquidation = 'on_liquidation'


class RuleTrigger(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    type: Type1
    timeframe: str | None = Field(None, description='Required for `on_bar_close`.')
    interval_ms: int | None = Field(None, description='Required for `on_timer`.', ge=100)
    cron: str | None = Field(None, description='Required for `on_schedule`; 5-field UTC cron.')
    metric: str | None = Field(None, description='Required for `on_metric_change`.')
    debounce_ms: int | None = Field(0, ge=0)


class IrVersion(IntEnum):
    integer_1 = 1


class RuleBindings(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    exchange_account_ids: list[UUID] | None = None
    symbols: list[Symbol] | None = None
    trade_group_ids: list[UUID] | None = None


class Editor(StrEnum):
    form = 'form'
    graph = 'graph'


class Tag(RootModel[str]):
    root: str = Field(..., max_length=40)


class Rule(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    mode: RuleMode
    scope: RuleScope
    editor: Editor | None = 'form'
    tags: list[str] | None = None
    active_version_id: UUID | None = None
    version: int | None = None
    bindings: RuleBindings | None = None
    last_run_at: AwareDatetime | None = None
    last_run_status: RuleRunStatus | None = None
    fire_count_24h: int | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class LastSimulation(BaseModel):
    run_id: UUID | None = None
    ir_hash: str | None = None
    completed_at: AwareDatetime | None = None
    fires: int | None = None


class RuleVersion(BaseModel):
    id: UUID | None = None
    rule_id: UUID | None = None
    version: int | None = None
    ir_hash: str | None = None
    is_active: bool | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    note: str | None = None


class Code(StrEnum):
    schema_error = 'schema_error'
    unknown_variable = 'unknown_variable'
    unknown_function = 'unknown_function'
    type_mismatch = 'type_mismatch'
    unreachable_branch = 'unreachable_branch'
    guard_missing = 'guard_missing'
    missing_action_param = 'missing_action_param'
    permission_required = 'permission_required'
    native_stop_missing = 'native_stop_missing'
    unsupported_symbol = 'unsupported_symbol'


class Severity1(StrEnum):
    error = 'error'
    warning = 'warning'


class Class(StrEnum):
    syntax = 'syntax'
    semantics = 'semantics'
    safety = 'safety'
    performance = 'performance'


class RuleValidationIssue(BaseModel):
    path: str | None = None
    code: Code | None = None
    message: str | None = None
    severity: Severity1 | None = None
    class_: Class | None = Field(None, alias='class')


class RuleValidationResult(BaseModel):
    valid: bool
    errors: list[RuleValidationIssue]
    warnings: list[RuleValidationIssue]
    referenced_variables: list[str] | None = None
    referenced_actions: list[str] | None = None
    estimated_evaluations_per_minute: int | None = None


class SimulateRuleRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    version_id: UUID | None = Field(None, description='Defaults to the active version.')
    from_: AwareDatetime | None = Field(None, alias='from')
    to: AwareDatetime | None = None
    replay_session_id: UUID | None = None
    symbols: list[Symbol] | None = None
    exchange_account_ids: list[UUID] | None = None
    speed: float | None = Field(0, ge=0.0, le=100.0)
    starting_equity_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Action1(BaseModel):
    ts: AwareDatetime | None = None
    action: str | None = None
    params: dict[str, Any] | None = None
    would_have_succeeded: bool | None = None
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    exchange_account_id: UUID | None = None


class RuleSimulationResult(BaseModel):
    run_id: UUID | None = None
    rule_id: UUID | None = None
    version_id: UUID | None = None
    from_: AwareDatetime | None = Field(None, alias='from')
    to: AwareDatetime | None = None
    evaluations: int | None = None
    fires: int | None = None
    suppressed_by_guard: int | None = None
    actions: list[Action1] | None = None
    hypothetical_pnl_delta_usd: Decimal | None = None
    errors: list[str] | None = None
    duration_ms: int | None = None


class Kind1(StrEnum):
    live = 'live'
    simulation = 'simulation'


class RuleRun(BaseModel):
    id: UUID | None = None
    rule_id: UUID | None = None
    rule_version_id: UUID | None = None
    kind: Kind1 | None = None
    status: RuleRunStatus | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    evaluations: int | None = None
    fires: int | None = None
    errors: int | None = None
    error_message: str | None = None


class Kind2(StrEnum):
    evaluated = 'evaluated'
    suppressed = 'suppressed'
    action_sent = 'action_sent'
    action_result = 'action_result'
    error = 'error'
    started = 'started'
    finished = 'finished'


class RuleEvent(BaseModel):
    id: int | None = None
    ts: AwareDatetime | None = None
    kind: Kind2 | None = None
    payload: dict[str, Any] | None = None


class TriggerMode(StrEnum):
    once = 'once'
    every_time = 'every_time'
    once_per_bar = 'once_per_bar'


class AlertDelivery(BaseModel):
    id: int | None = None
    alert_id: UUID | None = None
    channel: AlertChannel | None = None
    status: DeliveryStatus | None = None
    severity: Severity | None = None
    title: str | None = None
    message: str | None = None
    symbol: Symbol | None = None
    fired_at: AwareDatetime | None = None
    acked_at: AwareDatetime | None = None
    error: str | None = None


class Outcome(StrEnum):
    win = 'win'
    loss = 'loss'
    breakeven = 'breakeven'
    open = 'open'


class JournalTrade(BaseModel):
    id: UUID | None = None
    trade_group_id: UUID | None = None
    exchange_account_id: UUID | None = None
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: JournalSide | None = None
    opened_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_entry_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_exit_price: Decimal | None = None
    gross_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fees: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    r_multiple: Decimal | None = None
    max_favourable_excursion: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_adverse_excursion: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    duration_seconds: int | None = None
    outcome: Outcome | None = None
    rating: int | None = Field(None, ge=1, le=5)
    tags: list[str] | None = None
    setup: str | None = None
    notes_count: int | None = None


class Mistake(RootModel[str]):
    root: str = Field(..., max_length=120)


class UpdateJournalTradeRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    rating: int | None = Field(None, ge=1, le=5)
    tags: list[Tag] | None = None
    setup: str | None = Field(None, max_length=200)
    mistakes: list[Mistake] | None = None
    checklist: list[dict[str, Any]] | None = None


class NoteInput(BaseModel):
    body: str = Field(..., description='Markdown.', max_length=20000, min_length=1)
    snapshot_ref: str | None = Field(None, description='Reference to a stored chart snapshot.')


class Note(NoteInput):
    id: UUID | None = None
    author_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Totals1(BaseModel):
    trades: int | None = None
    wins: int | None = None
    losses: int | None = None
    breakeven: int | None = None
    win_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    gross_profit: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    gross_loss: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    net_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    fees: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    profit_factor: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    expectancy_r: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_win_r: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_loss_r: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_drawdown: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    max_drawdown_pct: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    longest_win_streak: int | None = None
    longest_loss_streak: int | None = None


class EquityCurveItem(BaseModel):
    t: AwareDatetime | None = None
    equity: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Row(BaseModel):
    key: str | None = None
    trades: int | None = None
    win_rate: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    net_pnl: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    expectancy_r: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Breakdown(BaseModel):
    group_by: str | None = None
    rows: list[Row] | None = None


class JournalAnalytics(BaseModel):
    totals: Totals1 | None = None
    equity_curve: list[EquityCurveItem] | None = None
    breakdowns: list[Breakdown] | None = None
    generated_at: AwareDatetime | None = None


class WorkspaceInput(BaseModel):
    name: str = Field(..., max_length=80, min_length=1)
    description: str | None = Field(None, max_length=280)
    is_default: bool | None = False


class Workspace(WorkspaceInput):
    id: UUID | None = None
    user_id: UUID | None = None
    layout_count: int | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Kind3(StrEnum):
    chart = 'chart'
    dom = 'dom'
    tape = 'tape'
    footprint = 'footprint'
    heatmap = 'heatmap'
    orders = 'orders'
    positions = 'positions'
    journal = 'journal'
    rules = 'rules'
    watchlist = 'watchlist'
    metrics = 'metrics'
    account_summary = 'account_summary'
    alerts = 'alerts'
    replay_controls = 'replay_controls'


class LinkGroup(Enum):
    """
    Panes sharing a colour follow each other's symbol and crosshair.
    """

    red = 'red'
    green = 'green'
    blue = 'blue'
    yellow = 'yellow'
    purple = 'purple'
    NoneType_None = None


class LayoutPane(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    slot: str = Field(
        ..., description='`column,row` grid position.', pattern='^[0-9]{1,2},[0-9]{1,2}$'
    )
    span: str | None = Field('1x1', pattern='^[0-9]{1,2}x[0-9]{1,2}$')
    kind: Kind3
    symbol: Symbol | None = None
    bar_type: BarType | None = None
    param: str | None = Field(None, max_length=24)
    depth: Depth | None = None
    chart_template_id: UUID | None = None
    link_group: LinkGroup | None = Field(
        None, description="Panes sharing a colour follow each other's symbol and crosshair."
    )
    settings: dict[str, Any] | None = None


class Grid(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    columns: int | None = Field(None, ge=1, le=8)
    rows: int | None = Field(None, ge=1, le=8)
    gaps_px: int | None = Field(4, ge=0, le=32)
    column_fractions: list[float] | None = None
    row_fractions: list[float] | None = None


class LayoutInput(BaseModel):
    name: str = Field(..., max_length=80, min_length=1)
    grid_preset: str | None = Field(None, examples=['1x1', '2x2', '3x1', 'custom'])
    grid: Grid | None = None
    panes: list[LayoutPane] = Field(..., max_length=32, min_length=1)
    is_default: bool | None = False


class Layout(LayoutInput):
    id: UUID | None = None
    workspace_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class ChartType(StrEnum):
    candlestick = 'candlestick'
    hollow_candlestick = 'hollow_candlestick'
    bar = 'bar'
    line = 'line'
    area = 'area'
    baseline = 'baseline'
    step_line = 'step_line'
    equi_volume = 'equi_volume'
    delta_volume = 'delta_volume'
    heikin_ashi = 'heikin_ashi'


class CellType(StrEnum):
    volume = 'volume'
    bid_ask = 'bid_ask'
    delta = 'delta'
    delta_total = 'delta_total'


class DisplayMode(StrEnum):
    profile = 'profile'
    box = 'box'


class Footprint(BaseModel):
    cell_type: CellType | None = None
    display_mode: DisplayMode | None = None
    price_grouping: int | None = None
    imbalance_ratio: float | None = None
    min_stack: int | None = None
    show_unfinished_auctions: bool | None = None


class Pane(StrEnum):
    main = 'main'
    sub1 = 'sub1'
    sub2 = 'sub2'
    sub3 = 'sub3'


class Indicator(BaseModel):
    code: str | None = None
    params: dict[str, Any] | None = None
    pane: Pane | None = None


class Mode(StrEnum):
    linear = 'linear'
    logarithmic = 'logarithmic'
    percent = 'percent'


class PriceScale(BaseModel):
    mode: Mode | None = None
    auto_fit: bool | None = None
    right_margin_bars: int | None = None


class Config(BaseModel):
    """
    Chart configuration blob; validated against the chart-engine schema in `26-chart-engine-design.md`.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    chart_type: ChartType | None = None
    bar_type: BarType | None = None
    param: str | None = None
    footprint: Footprint | None = None
    indicators: list[Indicator] | None = None
    colours: dict[str, str] | None = None
    price_scale: PriceScale | None = None


class ChartTemplateInput(BaseModel):
    name: str = Field(..., max_length=80, min_length=1)
    shared: bool | None = False
    config: Config = Field(
        ...,
        description='Chart configuration blob; validated against the chart-engine schema in `26-chart-engine-design.md`.',
    )


class ChartTemplate(ChartTemplateInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Tool(StrEnum):
    trendline = 'trendline'
    horizontal_line = 'horizontal_line'
    vertical_line = 'vertical_line'
    ray = 'ray'
    extended_line = 'extended_line'
    parallel_channel = 'parallel_channel'
    rectangle = 'rectangle'
    ellipse = 'ellipse'
    triangle = 'triangle'
    fib_retracement = 'fib_retracement'
    fib_extension = 'fib_extension'
    fib_timezone = 'fib_timezone'
    pitchfork = 'pitchfork'
    gann_fan = 'gann_fan'
    text = 'text'
    arrow = 'arrow'
    callout = 'callout'
    measure = 'measure'
    long_position = 'long_position'
    short_position = 'short_position'
    price_range = 'price_range'
    date_range = 'date_range'
    brush = 'brush'
    polyline = 'polyline'


class Point(BaseModel):
    t: AwareDatetime | None = None
    p: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class Geometry(BaseModel):
    """
    Chart-space geometry; points are `{t, p}` (time + price), never pixels.
    """

    model_config = ConfigDict(
        extra='allow',
    )
    points: list[Point] | None = None
    extend_left: bool | None = None
    extend_right: bool | None = None
    levels: list[float] | None = None
    text: str | None = None


class Dash(StrEnum):
    solid = 'solid'
    dashed = 'dashed'
    dotted = 'dotted'


class Style(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    colour: str | None = Field(None, pattern='^#[0-9a-fA-F]{6}$')
    fill_colour: str | None = Field(None, pattern='^#[0-9a-fA-F]{6}$')
    fill_opacity: float | None = Field(None, ge=0.0, le=1.0)
    width: int | None = Field(None, ge=1, le=8)
    dash: Dash | None = None
    label: str | None = Field(None, max_length=120)
    font_size: int | None = Field(None, ge=8, le=48)


class DrawingInput(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    tool: Tool
    layout_id: UUID | None = None
    bar_type_binding: str | None = Field(
        None, description='`{bar_type}:{param}` when the drawing is pinned to one bar construction.'
    )
    geometry: Geometry = Field(
        ..., description='Chart-space geometry; points are `{t, p}` (time + price), never pixels.'
    )
    style: Style | None = None
    locked: bool | None = False
    visible: bool | None = True


class Drawing(DrawingInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class IndicatorPresetInput(BaseModel):
    name: str = Field(..., max_length=80, min_length=1)
    indicator_code: str = Field(..., max_length=40)
    params: dict[str, Any]
    is_default: bool | None = False


class IndicatorPreset(IndicatorPresetInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class Theme(StrEnum):
    dark = 'dark'
    light = 'light'
    system = 'system'


class Density(StrEnum):
    compact = 'compact'
    comfortable = 'comfortable'
    spacious = 'spacious'


class Appearance(BaseModel):
    theme: Theme | None = None
    density: Density | None = None
    font_scale: float | None = Field(None, ge=0.75, le=2.0)
    reduce_motion: bool | None = None
    high_contrast: bool | None = None


class PriceScaleMode(StrEnum):
    linear = 'linear'
    logarithmic = 'logarithmic'
    percent = 'percent'


class Chart(BaseModel):
    default_bar_type: BarType | None = None
    default_param: str | None = None
    crosshair_sync: bool | None = None
    bar_close_countdown: bool | None = None
    price_scale_mode: PriceScaleMode | None = None


class BigTradeThresholdMode(StrEnum):
    absolute = 'absolute'
    relative = 'relative'
    zscore = 'zscore'


class Orderflow(BaseModel):
    heatmap_bid_colour: str | None = None
    heatmap_ask_colour: str | None = None
    imbalance_ratio: float | None = None
    min_stack: int | None = None
    value_area_pct: float | None = None
    big_trade_threshold_mode: BigTradeThresholdMode | None = None
    big_trade_k: float | None = None


class Trading(BaseModel):
    one_click_armed: bool | None = None
    arm_timeout_seconds: int | None = None
    confirm_market_orders: bool | None = None
    confirm_flatten: bool | None = None
    default_environment: Environment | None = None
    default_qty_presets: list[Decimal] | None = None


class Notifications(BaseModel):
    desktop_enabled: bool | None = None
    email_enabled: bool | None = None
    webhook_url: str | None = None
    quiet_hours: dict[str, Any] | None = None


class Data(BaseModel):
    default_depth: int | None = None
    stale_badge_after_ms: int | None = None
    max_history_bars: int | None = None


class FieldMeta(BaseModel):
    overridden: list[str] | None = None
    updated_at: AwareDatetime | None = None


class Settings(BaseModel):
    """
    Effective settings — deployment defaults overlaid with user overrides.
    """

    appearance: Appearance | None = None
    chart: Chart | None = None
    orderflow: Orderflow | None = None
    trading: Trading | None = None
    notifications: Notifications | None = None
    data: Data | None = None
    field_meta: FieldMeta | None = Field(None, alias='_meta')


class SettingsPatch(BaseModel):
    """
    Deep-merge patch; only present leaves change. `null` resets a leaf to the deployment default.
    """

    model_config = ConfigDict(
        extra='allow',
    )


class Scope2(StrEnum):
    global_ = 'global'
    chart = 'chart'
    dom = 'dom'
    tape = 'tape'
    orders = 'orders'
    positions = 'positions'


class HotkeyBinding(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    action: str = Field(
        ...,
        examples=['order.buy_market', 'position.flatten', 'chart.toggle_footprint'],
        max_length=60,
    )
    keys: str = Field(
        ...,
        description='Chord notation, e.g. `Ctrl+Shift+F` or a sequence `Esc Esc`.',
        max_length=60,
    )
    scope: Scope2
    requires_arm: bool | None = Field(True, description='Forced true for order-sending actions.')
    confirm: bool | None = False
    params: dict[str, Any] | None = None


class HotkeyProfileInput(BaseModel):
    name: str = Field(..., max_length=80, min_length=1)
    bindings: list[HotkeyBinding] = Field(..., max_length=200)


class HotkeyProfile(HotkeyProfileInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    is_active: bool | None = None
    updated_at: AwareDatetime | None = None


class AuditEntry(BaseModel):
    id: int | None = None
    ts: AwareDatetime | None = None
    actor_user_id: UUID | None = None
    actor_username: str | None = None
    action: str | None = None
    subject_type: str | None = None
    subject_id: str | None = None
    outcome: AuditOutcome | None = None
    severity: Severity | None = None
    ip: str | None = None
    user_agent: str | None = None
    request_id: str | None = None
    detail: dict[str, Any] | None = None
    entry_hash: str | None = None
    prev_hash: str | None = None


class Component(BaseModel):
    name: str | None = None
    state: ComponentState | None = None
    latency_ms: int | None = None
    detail: str | None = None


class HealthReport(BaseModel):
    overall: ComponentState | None = None
    version: str | None = None
    git_sha: str | None = None
    uptime_seconds: int | None = None
    server_time: AwareDatetime | None = None
    clock_offset_ms: int | None = None
    components: list[Component] | None = None
    alerts_active: int | None = None


class Override(BaseModel):
    user_id: UUID | None = None
    value: Any | None = None


class FeatureFlag(BaseModel):
    key: str | None = None
    kind: FlagKind | None = None
    description: str | None = None
    value: Any | None = Field(None, description='Resolved value for the caller.')
    default_value: Any | None = Field(None, description='Deployment default.')
    overrides: list[Override] | None = None
    updated_by: UUID | None = None
    updated_at: AwareDatetime | None = None


class Override1(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    user_id: UUID
    value: Any


class SetFeatureFlagRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    value: Any = Field(
        ..., description='Boolean, number (percentage) or string (variant), matching the flag kind.'
    )
    overrides: list[Override1] | None = None
    reason: str | None = Field(None, max_length=280)
    evidence_url: AnyUrl | None = Field(
        None, description='Required for gated flags such as `trading.live_enabled`.'
    )


class Backup(BaseModel):
    id: UUID | None = None
    kind: BackupKind | None = None
    status: BackupStatus | None = None
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    size_bytes: int | None = None
    location: str | None = None
    checksum_sha256: str | None = None
    encrypted: bool | None = None
    retention_until: AwareDatetime | None = None
    verified_at: AwareDatetime | None = None
    error: str | None = None


class Kind4(StrEnum):
    instrument_refresh = 'instrument_refresh'
    audit_export = 'audit_export'
    backup = 'backup'
    backup_verify = 'backup_verify'
    rule_simulation = 'rule_simulation'
    retention_sweep = 'retention_sweep'
    reconciliation = 'reconciliation'


class Status1(StrEnum):
    queued = 'queued'
    running = 'running'
    succeeded = 'succeeded'
    failed = 'failed'
    cancelled = 'cancelled'


class Job(BaseModel):
    id: UUID | None = None
    kind: Kind4 | None = None
    status: Status1 | None = None
    progress_pct: float | None = Field(None, ge=0.0, le=100.0)
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    result: dict[str, Any] | None = None
    error: str | None = None


class Mode1(StrEnum):
    read = 'read'
    trade = 'trade'


class Account1(BaseModel):
    exchange_account_id: UUID
    label: str | None = None
    environment: Environment | None = None
    mode: Mode1


class Session(BaseModel):
    session_id: UUID | None = None
    environment: Environment | None = None
    elevated_until: AwareDatetime | None = None
    one_click_armed_until: AwareDatetime | None = None


class Me(BaseModel):
    user: User
    role: RoleName
    permissions: list[str] = Field(
        ...,
        description='Flattened effective permissions, drawn from the same closed vocabulary as `x-rbac.permissions` on every operation in this file.\n',
    )
    accounts: list[Account1] = Field(
        ..., description='Accounts the caller may see, with the granted mode.'
    )
    session: Session | None = None
    onboarding_complete: bool | None = None


class Account2(BaseModel):
    exchange_account_id: UUID | None = None
    orders_per_minute_limit: int | None = None
    orders_per_minute_used: int | None = None
    rate_budget_pct_used: float | None = Field(None, ge=0.0, le=100.0)
    daily_loss_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    daily_loss_cap_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_positions: int | None = None
    lockout_until: AwareDatetime | None = None


class EffectiveLimits(BaseModel):
    risk_caps: RiskCaps | None = None
    accounts: list[Account2] | None = None


class Key(StrEnum):
    mfa_enrolled = 'mfa_enrolled'
    exchange_account_added = 'exchange_account_added'
    api_key_verified = 'api_key_verified'
    symbol_recorded = 'symbol_recorded'
    workspace_created = 'workspace_created'
    demo_order_placed = 'demo_order_placed'


class Item(BaseModel):
    key: Key
    satisfied: bool
    detail: str | None = None
    action_route: str | None = None


class OnboardingChecklist(BaseModel):
    complete: bool | None = None
    items: list[Item] | None = None


class Kind5(StrEnum):
    alert = 'alert'
    rule = 'rule'
    order = 'order'
    risk = 'risk'
    system = 'system'


class Notification(BaseModel):
    id: UUID
    kind: Kind5
    severity: Severity
    title: str
    body: str | None = None
    created_at: AwareDatetime
    read_at: AwareDatetime | None = None
    symbol: str | None = None
    exchange_account_id: UUID | None = None
    source_id: UUID | None = Field(
        None, description='Id of the originating alert delivery, rule event, order or system event.'
    )
    route: str | None = Field(
        None, description='Deep link to the screen that explains this notification.'
    )


class WatchlistInput(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    name: str = Field(..., max_length=80, min_length=1)
    symbols: list[Symbol] = Field(..., max_length=200)
    columns: list[str] | None = Field(
        None, description='Column ids shown for this watchlist, in order.'
    )


class Coverage(StrEnum):
    """
    `live_only` means no local history exists for this symbol, so criteria that need recorded history were skipped for this row rather than evaluated as zero.

    """

    recorded = 'recorded'
    live_only = 'live_only'


class ScannerRow(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    last_price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    price_change_pct_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    volume_24h: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_interest: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cvd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    tape_speed: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    liquidation_intensity: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    recording: bool | None = None
    coverage: Coverage = Field(
        ...,
        description='`live_only` means no local history exists for this symbol, so criteria that need recorded history were skipped for this row rather than evaluated as zero.\n',
    )


class Category(StrEnum):
    trend = 'trend'
    momentum = 'momentum'
    volatility = 'volatility'
    volume = 'volume'
    orderflow = 'orderflow'


class Pane1(StrEnum):
    price = 'price'
    sub = 'sub'
    both = 'both'


class Compute(StrEnum):
    """
    `server` indicators are read from `orderflow_metrics` and require recorded history; `client_worker` indicators are computed from bars already in the client.

    """

    client_worker = 'client_worker'
    server = 'server'


class IndicatorDescriptor(BaseModel):
    id: str
    name: str
    category: Category | None = None
    pane: Pane1
    compute: Compute = Field(
        ...,
        description='`server` indicators are read from `orderflow_metrics` and require recorded history; `client_worker` indicators are computed from bars already in the client.\n',
    )
    estimated: bool | None = Field(
        False, description='True for heuristic signals that infer unobservable intent.'
    )
    params_schema: dict[str, Any] = Field(
        ...,
        description="JSON Schema for this indicator's parameters; the settings form renders from it.",
    )
    defaults: dict[str, Any] | None = None


class LayoutPreset(BaseModel):
    id: UUID
    name: str
    description: str | None = None
    is_builtin: bool
    pane_count: int | None = None
    preview_svg: str | None = None
    layout: LayoutInput | None = None


class WorkspaceBundle(BaseModel):
    """
    Portable, credential-free export of presentation state only.

    """

    schema_version: str
    exported_at: AwareDatetime | None = None
    workspace: WorkspaceInput
    layouts: list[LayoutInput]
    chart_templates: list[ChartTemplateInput] | None = None
    drawings: list[DrawingInput] | None = None
    indicator_presets: list[IndicatorPresetInput] | None = None


class ExchangeCall(BaseModel):
    at: AwareDatetime | None = None
    endpoint: str | None = None
    http_status: int | None = None
    ret_code: int | None = None
    ret_msg: str | None = None
    latency_ms: int | None = None
    request_redacted: dict[str, Any] | None = None
    response_redacted: dict[str, Any] | None = None


class Verdict(StrEnum):
    in_sync = 'in_sync'
    drifted = 'drifted'
    repaired = 'repaired'
    unresolvable = 'unresolvable'


class Reconciliation(BaseModel):
    last_checked_at: AwareDatetime | None = None
    verdict: Verdict | None = None
    detail: str | None = None


class OrderDiagnostics(BaseModel):
    order: Order
    events: list[OrderEvent]
    exchange_calls: list[ExchangeCall] | None = Field(
        None,
        description='Request/response pairs with credentials, signatures and headers redacted.',
    )
    reconciliation: Reconciliation | None = None


class Code1(StrEnum):
    cap_breached = 'cap_breached'
    symbol_not_allowed = 'symbol_not_allowed'
    insufficient_margin = 'insufficient_margin'
    rate_budget_exhausted = 'rate_budget_exhausted'
    account_locked = 'account_locked'
    key_invalid = 'key_invalid'
    leverage_unavailable = 'leverage_unavailable'
    kill_switch_engaged = 'kill_switch_engaged'


class Rejection(BaseModel):
    code: Code1 | None = None
    message: str | None = None


class Leg1(BaseModel):
    exchange_account_id: UUID
    account_label: str | None = None
    account_profile_id: UUID | None = None
    would_submit: bool
    resolved: ResolvedLegParams | None = None
    estimated_margin_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    estimated_risk_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    rejection: Rejection | None = None


class Totals2(BaseModel):
    accounts_targeted: int | None = None
    accounts_submittable: int | None = None
    total_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    total_notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    total_risk_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )


class TradeGroupPreview(BaseModel):
    """
    What `POST /trade-groups` would do, without doing it. Mirrors the resolved leg shape used in `TradeGroup.legs` so the ticket renders the preview and the result with one component.

    """

    legs: list[Leg1]
    totals: Totals2


class Scope3(StrEnum):
    global_ = 'global'
    accounts = 'accounts'


class Totals3(BaseModel):
    equity_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unrealised_pnl_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl_today_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    open_positions: int | None = None
    gross_notional_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    positions_without_native_stop: int | None = Field(
        None,
        description='MUST be zero in steady state; any non-zero value is a violation of the native-stop safety invariant and is surfaced as a critical banner.\n',
    )


class Reason1(StrEnum):
    daily_loss = 'daily_loss'
    consecutive_losses = 'consecutive_losses'
    max_positions = 'max_positions'
    manual = 'manual'


class Lockout(BaseModel):
    reason: Reason1 | None = None
    since: AwareDatetime | None = None
    until: AwareDatetime | None = None


class Account3(BaseModel):
    exchange_account_id: UUID | None = None
    label: str | None = None
    equity_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    unrealised_pnl_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    realised_pnl_today_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    daily_loss_cap_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    cap_utilisation_pct: float | None = Field(None, ge=0.0)
    open_positions: int | None = None
    frozen: bool | None = None
    lockout: Lockout | None = None


class RiskSummary(BaseModel):
    scope: Scope3
    environment: Environment | None = None
    kill_switch: KillSwitch | None = None
    totals: Totals3 | None = None
    accounts: list[Account3]


class Iceberg1(BaseModel):
    enabled: bool | None = True
    min_reloads: int | None = Field(3, ge=2, le=50)
    price_tolerance_ticks: int | None = Field(0, ge=0, le=10)
    window_ms: int | None = Field(5000, ge=200, le=60000)


class StopRun(BaseModel):
    enabled: bool | None = True
    lookback_bars: int | None = Field(20, ge=2, le=500)
    penetration_ticks: int | None = Field(2, ge=1, le=100)
    reversal_pct: float | None = Field(60, ge=0.0, le=100.0)


class Absorption(BaseModel):
    enabled: bool | None = True
    min_volume_multiple: float | None = Field(3, ge=1.0, le=50.0)
    max_price_move_ticks: int | None = Field(1, ge=0, le=50)


class Exhaustion(BaseModel):
    enabled: bool | None = True
    min_delta_divergence: float | None = Field(0.5, ge=0.0)


class Mode2(StrEnum):
    absolute_usd = 'absolute_usd'
    percentile = 'percentile'


class BigTrade(BaseModel):
    mode: Mode2 | None = 'percentile'
    absolute_usd: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    percentile: float | None = Field(99, ge=50.0, le=99.99)


class DetectorConfig(BaseModel):
    """
    Thresholds for the estimated detectors. Every detector here is a heuristic over anonymous public data; changing a threshold changes sensitivity, never correctness.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    iceberg: Iceberg1 | None = None
    stop_run: StopRun | None = None
    absorption: Absorption | None = None
    exhaustion: Exhaustion | None = None
    big_trade: BigTrade | None = None


class Detector(StrEnum):
    iceberg = 'iceberg'
    stop_run = 'stop_run'
    absorption = 'absorption'
    exhaustion = 'exhaustion'
    big_trade = 'big_trade'
    regime = 'regime'


class DetectorMethodology(BaseModel):
    detector: Detector
    display_name: str | None = None
    inputs: list[str]
    assumption: str = Field(..., description='The inference being made, stated plainly.')
    false_positive_modes: list[str]
    confidence_basis: str | None = None


class Regime(StrEnum):
    trending_up = 'trending_up'
    trending_down = 'trending_down'
    ranging = 'ranging'
    volatile_expansion = 'volatile_expansion'
    compression = 'compression'


class Direction2(StrEnum):
    supports = 'supports'
    opposes = 'opposes'
    neutral = 'neutral'


class Signal(BaseModel):
    name: str | None = None
    value: float | None = None
    weight: float | None = None
    contribution: float | None = None
    direction: Direction2 | None = None


class RegimeExplanation(BaseModel):
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    regime: Regime
    confidence: float | None = Field(None, ge=0.0, le=1.0)
    as_of: AwareDatetime | None = None
    signals: list[Signal]


class Type2(StrEnum):
    number = 'number'
    boolean = 'boolean'
    price = 'price'
    quantity = 'quantity'
    duration = 'duration'
    enum = 'enum'


class Signal1(BaseModel):
    id: str
    display_name: str | None = None
    type: Type2
    unit: str | None = None
    enum_values: list[str] | None = None
    params_schema: dict[str, Any] | None = None
    requires_recording: bool | None = False
    estimated: bool | None = False


class Operator(BaseModel):
    id: str | None = None
    arity: int | None = Field(None, ge=1, le=3)
    operand_types: list[str] | None = None
    result_type: str | None = None


class Action2(BaseModel):
    id: str
    display_name: str | None = None
    params_schema: dict[str, Any] | None = None
    required_permissions: list[str]
    requires_step_up: bool | None = False
    loosens_risk: bool | None = Field(
        False,
        description='Actions that can widen or remove a stop are flagged so the editors can warn and the engine can gate them behind the owner-only permission.\n',
    )


class Guard(BaseModel):
    id: str | None = None
    params_schema: dict[str, Any] | None = None


class RuleVocabulary(BaseModel):
    """
    The closed vocabulary shared by the form editor, the node-graph editor and the rule engine. Anything absent from this response is not expressible in the IR.

    """

    ir_version: str | None = None
    signals: list[Signal1]
    operators: list[Operator]
    actions: list[Action2]
    guards: list[Guard]


class Kind6(StrEnum):
    entry = 'entry'
    exit = 'exit'
    stop_moved = 'stop_moved'
    scale_in = 'scale_in'
    scale_out = 'scale_out'
    rule_fired = 'rule_fired'


class Marker(BaseModel):
    at: AwareDatetime | None = None
    kind: Kind6 | None = None
    price: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    label: str | None = None


class JournalTradeContext(BaseModel):
    journal_trade_id: UUID
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    from_: AwareDatetime = Field(..., alias='from')
    to: AwareDatetime
    bars: list[Bar] | None = None
    footprint: list[FootprintBar] | None = None
    executions: list[Execution] | None = None
    markers: list[Marker] | None = None
    coverage: DataCoverage


class BuildInfo(BaseModel):
    version: str
    commit: str
    built_at: AwareDatetime
    api_version: str | None = None
    ws_protocol_version: str | None = None
    electron_version: str | None = None


class Users(BaseModel):
    total: int | None = None
    active: int | None = None
    without_mfa: int | None = None


class Accounts(BaseModel):
    total: int | None = None
    enabled: int | None = None
    keys_expiring_30d: int | None = None
    keys_invalid: int | None = None


class Recorder(BaseModel):
    symbols_recording: int | None = None
    symbols_degraded: int | None = None
    lag_seconds_p99: float | None = None


class Storage(BaseModel):
    used_bytes: int | None = None
    free_bytes: int | None = None
    days_until_full: float | None = None


class Trading1(BaseModel):
    live_enabled: bool | None = None
    kill_switch_engaged: bool | None = None
    open_positions: int | None = None


class AdminOverview(BaseModel):
    users: Users | None = None
    accounts: Accounts | None = None
    recorder: Recorder | None = None
    storage: Storage | None = None
    trading: Trading1 | None = None
    incidents_open: int | None = None


class PerSymbolItem(BaseModel):
    symbol: str | None = Field(
        None,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    used_bytes: int | None = None
    daily_growth_bytes: int | None = None
    pinned: bool | None = None
    retention_days: int | None = None


class Storage1(BaseModel):
    used_bytes: int | None = None
    free_bytes: int | None = None
    daily_growth_bytes: int | None = None
    days_until_full: float | None = None
    per_symbol: list[PerSymbolItem] | None = None


class Ingestion(BaseModel):
    messages_per_sec: float | None = None
    queue_depth: int | None = None
    dropped_last_hour: int | None = None


class RateBudgetItem(BaseModel):
    exchange_account_id: UUID | None = None
    label: str | None = None
    limit_per_minute: int | None = None
    peak_used_per_minute: int | None = None
    utilisation_pct: float | None = None


class CapacityReport(BaseModel):
    storage: Storage1 | None = None
    ingestion: Ingestion | None = None
    rate_budget: list[RateBudgetItem] | None = None


class Status2(StrEnum):
    open = 'open'
    acknowledged = 'acknowledged'
    resolved = 'resolved'


class Incident(BaseModel):
    id: UUID
    component: str
    severity: Severity
    status: Status2
    title: str | None = None
    detail: str | None = None
    occurrences: int | None = None
    first_seen_at: AwareDatetime
    last_seen_at: AwareDatetime
    acknowledged_by: UUID | None = None
    resolved_at: AwareDatetime | None = None
    runbook_ref: str | None = None


class Key1(BaseModel):
    exchange_account_id: UUID | None = None
    key_id_prefix: str | None = None
    status: KeyStatus | None = None
    age_days: int | None = None
    expires_at: AwareDatetime | None = None
    withdrawal_permission_present: bool | None = Field(
        None, description='MUST be false; true raises a critical finding immediately.'
    )
    ip_whitelist_matches_expected: bool | None = None
    last_verified_at: AwareDatetime | None = None


class Auth(BaseModel):
    users_without_mfa: int | None = None
    failed_logins_24h: int | None = None
    denied_requests_24h: int | None = None
    active_elevated_sessions: int | None = None


class Audit(BaseModel):
    last_chain_verification_at: AwareDatetime | None = None
    chain_intact: bool | None = None
    entries_total: int | None = None


class Finding(BaseModel):
    severity: Severity | None = None
    code: str | None = None
    message: str | None = None


class SecuritySummary(BaseModel):
    generated_at: AwareDatetime | None = None
    keys: list[Key1] | None = None
    auth: Auth | None = None
    audit: Audit | None = None
    findings: list[Finding] | None = None


class AuthenticatedResponse(BaseModel):
    status: Literal['authenticated']
    tokens: TokenBundle
    user: User


class LoginResponse(RootModel[AuthenticatedResponse | MfaChallengeResponse]):
    root: AuthenticatedResponse | MfaChallengeResponse = Field(..., discriminator='status')


class SessionInfo(BaseModel):
    user: User
    permissions: list[str]
    account_scope: list[UUID]
    allowed_environments: list[Environment] | None = None
    kill_switch: KillSwitch | None = None
    server_time: AwareDatetime
    clock_offset_ms: int | None = Field(
        None,
        description='Backend clock minus Bybit server time; |offset| > 1000 ms is an incident.',
    )
    api_version: str | None = None
    feature_flags: dict[str, Any] | None = Field(None, description='Flags resolved for this user.')


class CreateUserRequest(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    username: str = Field(..., max_length=40, min_length=3, pattern='^[a-zA-Z0-9._-]+$')
    email: EmailStr
    display_name: str | None = Field(None, max_length=80)
    roles: list[RoleName] = Field(..., min_length=1)
    mfa_required: bool | None = True
    account_access: list[AccountAccessGrantInput] | None = None


class ExchangeAccount(BaseModel):
    id: UUID
    exchange: ExchangeCode
    environment: Environment
    kind: AccountKind
    label: str = Field(..., max_length=80)
    exchange_uid: str
    parent_account_id: UUID | None = None
    connection_state: ConnectionState | None = None
    key_status: KeyStatus1 | None = None
    position_mode: PositionMode | None = None
    margin_mode: MarginMode | None = None
    active_profile_id: UUID | None = None
    balance: WalletBalance | None = None
    balance_stale: bool | None = None
    enabled: bool | None = True
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class OrderWithEvents(Order):
    events: list[OrderEvent] | None = None
    executions: list[Execution] | None = None


class TradeGroupLeg(BaseModel):
    """
    One account's share of a fan-out. Field names mirror the `trade_group_legs` columns in 21-database-schema.md §3.3.3 one-for-one; the only additions are `orders` (the leg's order ids, a join rather than a column) and `resolved` (the computed parameters, stored as `resolved_*` columns and the `profile_snapshot` JSONB).

    """

    id: UUID | None = None
    trade_group_id: UUID | None = None
    exchange_account_id: UUID | None = None
    account_profile_id: UUID | None = Field(
        None,
        description='The profile that produced `resolved`. Null when the ticket overrode the profile entirely.',
    )
    status: LegStatus | None = None
    sequence_no: int | None = Field(
        None,
        description='Deterministic submission order within the group, so a partial fan-out is reproducible.',
    )
    resolved: ResolvedLegParams | None = None
    orders: list[UUID] | None = None
    target_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    filled_qty: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    avg_entry_price: Decimal | None = None
    avg_exit_price: Decimal | None = None
    native_sl_confirmed: bool | None = Field(
        None,
        description='True once the exchange has acknowledged a native stop-loss on this leg. The safety invariant (arch P4) requires this to become true for every filled leg; a filled leg with `false` is an alertable condition, not a cosmetic gap.\n',
    )
    native_sl_confirmed_at: AwareDatetime | None = None
    risk_usd: Decimal | None = None
    realised_pnl: Decimal | None = None
    fees_paid: str | None = Field(
        None,
        description='Arbitrary-precision decimal transported as a string (convention C6).',
        examples=['63120.50', '-0.0004', '0'],
        pattern='^-?[0-9]+(\\.[0-9]+)?$',
    )
    error: LegError | None = None
    submitted_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class TradeGroup(BaseModel):
    is_paper: bool | None = Field(
        False,
        description='True when the paper matcher produced this record rather than the exchange. Orthogonal to `environment` (24-internal-schemas.md section 1.2).',
    )
    id: UUID
    client_group_ref: str | None = None
    symbol: str = Field(
        ...,
        description='Bybit USDT linear perpetual symbol. v1 accepts USDT-quoted linear symbols only.',
        examples=['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        pattern='^[A-Z0-9]{2,20}USDT$',
    )
    side: OrderSide
    intent: OrderIntent | None = None
    status: TradeGroupStatus
    atomicity: Atomicity | None = 'best_effort'
    algo: AlgoSpec | None = None
    rule_id: UUID | None = None
    created_by: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None
    closed_at: AwareDatetime | None = None
    note: str | None = None
    legs: list[TradeGroupLeg]
    totals: Totals | None = None


class JournalTradeDetail(JournalTrade):
    mistakes: list[str] | None = None
    checklist: list[dict[str, Any]] | None = None
    executions: list[Execution] | None = None
    notes: list[Note] | None = None
    rule_id: UUID | None = None


class WorkspaceDetail(Workspace):
    layouts: list[Layout] | None = None


class Watchlist(WatchlistInput):
    id: UUID | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


class RuleArithmeticNode(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    node_id: str
    op: Op
    operands: list[RuleMetricRef | RuleOperand1 | RuleArithmeticNode] = Field(
        ..., max_length=8, min_length=1
    )


class RuleComparisonNode(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    node_id: str
    op: Op1
    left: RuleMetricRef | RuleOperand1 | RuleArithmeticNode = Field(
        ...,
        description='A value position in the condition tree. Exactly one form is present:\na metric reference, a constant, or an arithmetic node.\n',
    )
    right: RuleMetricRef | RuleOperand1 | RuleArithmeticNode | None = Field(
        None,
        description='A value position in the condition tree. Exactly one form is present:\na metric reference, a constant, or an arithmetic node.\n',
    )
    right2: RuleMetricRef | RuleOperand1 | RuleArithmeticNode | None = Field(
        None, description='Upper bound for `between` / `outside`.'
    )
    set_values: list[str] | None = None
    tolerance: float | None = Field(None, description='Equality tolerance for float comparisons.')


class RuleBooleanNode(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    node_id: str
    op: Op2
    children: list[RuleComparisonNode | RuleBooleanNode | RuleTemporalNode] = Field(
        ..., max_length=32, min_length=1
    )
    n: int | None = Field(None, description='Required for `n_of`.', ge=1)


class RuleTemporalNode(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    node_id: str
    op: Op3
    child: RuleComparisonNode | RuleBooleanNode | RuleTemporalNode = Field(
        ...,
        description='A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR.\n',
    )
    window_ms: int = Field(..., ge=100, le=86400000)
    min_count: int | None = Field(1, ge=1)


class RuleIr(BaseModel):
    """
    The single executable representation produced by **both** the form editor and the
    node-graph editor (owner decision #11). Round-tripping is lossless because
    `graph_layout` (cosmetic node coordinates) is stored on the rule, outside the IR,
    so compiling either editor's model yields a byte-identical IR and therefore an
    identical `ir_hash`.

    This object is the *executable core only*. Rule identity and lifecycle
    (`id`, `name`, `mode`, `scope`, `editor`, `version`) live on `Rule` / `RuleInput`
    and in the `rules` table - they are deliberately not duplicated here, so an IR can
    be validated, hashed and compared without carrying database identity.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    ir_version: IrVersion
    trigger: RuleTrigger
    conditions: RuleComparisonNode | RuleBooleanNode | RuleTemporalNode = Field(
        ...,
        description='A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR.\n',
    )
    actions: list[RuleAction] = Field(..., max_length=10, min_length=1)
    limits: RuleLimits | None = None
    variables: dict[str, RuleMetricRef | RuleOperand1 | RuleArithmeticNode] | None = Field(
        None, description='Named intermediate expressions, evaluated before `conditions`.'
    )


class AlertConditionIr(BaseModel):
    """
    The condition half of the rule IR, reused by alerts. Alerts have no `actions` block
    - the action is always "notify on the configured channels", so an alert can never
    place an order regardless of what the user authors.

    """

    model_config = ConfigDict(
        extra='forbid',
    )
    ir_version: IrVersion
    trigger: RuleTrigger
    conditions: RuleComparisonNode | RuleBooleanNode | RuleTemporalNode = Field(
        ...,
        description='A node in the boolean DAG: a comparison leaf, a boolean combinator, or a temporal window. Every node carries a stable `node_id`, which is what lets the node-graph editor attach coordinates in `graph_layout` without putting cosmetics in the IR.\n',
    )
    variables: dict[str, RuleMetricRef | RuleOperand1 | RuleArithmeticNode] | None = None
    limits: RuleLimits | None = None


class RuleInput(BaseModel):
    model_config = ConfigDict(
        extra='forbid',
    )
    name: str = Field(..., max_length=120, min_length=1)
    description: str | None = Field(None, max_length=1000)
    scope: RuleScope
    editor: Editor | None = 'form'
    tags: list[Tag] | None = None
    bindings: RuleBindings | None = None
    ir: RuleIr
    graph_layout: dict[str, Any] | None = Field(
        None, description='Node/edge coordinates for the node-graph editor. Ignored by the engine.'
    )
    note: str | None = Field(None, max_length=280)


class RuleDetail(Rule):
    ir: RuleIr | None = None
    graph_layout: dict[str, Any] | None = None
    ir_hash: str | None = None
    last_simulation: LastSimulation | None = None


class RuleVersionDetail(RuleVersion):
    ir: RuleIr | None = None
    graph_layout: dict[str, Any] | None = None


class AlertInput(BaseModel):
    name: str = Field(..., max_length=120, min_length=1)
    symbol: Symbol | None = None
    exchange_account_id: UUID | None = None
    trigger_mode: TriggerMode | None = 'once'
    channels: list[AlertChannel] = Field(..., min_length=1)
    condition_ir: AlertConditionIr
    message_template: str | None = Field(
        None,
        description='Mustache-style placeholders resolved from the rule context.',
        max_length=500,
    )
    severity: Severity | None = None
    expires_at: AwareDatetime | None = None
    webhook_url: AnyUrl | None = None
    enabled: bool | None = True


class Alert(AlertInput):
    id: UUID | None = None
    owner_user_id: UUID | None = None
    fire_count: int | None = None
    last_fired_at: AwareDatetime | None = None
    created_at: AwareDatetime | None = None
    updated_at: AwareDatetime | None = None


RuleArithmeticNode.model_rebuild()
RuleBooleanNode.model_rebuild()
RuleTemporalNode.model_rebuild()
