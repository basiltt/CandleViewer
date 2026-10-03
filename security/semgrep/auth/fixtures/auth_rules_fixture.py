"""Fixtures for the E09-X03 auth Semgrep pack: positive (`ruleid`) and negative (`ok`).

Never imported or run -- only scanned by tools/ci/check_auth_semgrep.py.
"""
# ruff: noqa
# fmt: off


# --- no-raw-account-id (SR-051) -------------------------------------------
@router.get("/positions")  # ruleid: no-raw-account-id
async def positions_bad(account_id: str):
    return await repo.positions(account_id)


@router.get("/orders")  # ok: no-raw-account-id
async def orders_ok(account_id: str, scope):
    allowed = scope.intersect(account_id)
    return await repo.orders(allowed)


# --- no-adhoc-authz (SR-017) ----------------------------------------------
def adhoc_bad(principal):
    if principal.role == "owner":  # ruleid: no-adhoc-authz
        return True
    return False


def adhoc_ok(principal):
    return authorize(principal, "orders.read", None)  # ok: no-adhoc-authz


# --- no-target-user-on-self-service (SR-026) ------------------------------
@router.post("/me/password")  # ruleid: no-target-user-on-self-service
async def me_bad(user_id: str):
    return None


@router.post("/me/sessions")  # ok: no-target-user-on-self-service
async def me_ok(principal):
    return None


@router.get("/users/{user_id}")  # ok: no-target-user-on-self-service
async def admin_get_user(user_id: str):
    return None


# --- stepup-required (SR-025) ---------------------------------------------
@router.post("/admin/kill-switch")  # ruleid: stepup-required
async def kill_bad():
    return None


@router.post("/admin/kill-switch/arm", dependencies=[Depends(require_step_up("kill"))])  # ok: stepup-required
async def kill_ok():
    return None


# --- no-secret-logging (SR-122) -------------------------------------------
def log_bad(logger, session_token):
    logger.info("login", session_token)  # ruleid: no-secret-logging


def log_fstring_bad(logger, recovery_code):
    logger.warning(f"bad code {recovery_code}")  # ruleid: no-secret-logging


def log_ok(logger, user_id):
    logger.info("login", user_id=user_id)  # ok: no-secret-logging


# --- cookie-flags (SR-012) ------------------------------------------------
def cookie_bad(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True)  # ruleid: cookie-flags


def cookie_domain_bad(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="strict", domain=".x.io")  # ruleid: cookie-flags-domain


def cookie_domain_ok(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="strict")  # ok: cookie-flags-domain


def cookie_ok(response, sid):
    response.set_cookie("cv_refresh", sid, httponly=True, secure=True, samesite="strict")  # ok: cookie-flags


# --- argon2-params (SR-011) -----------------------------------------------
weak = PasswordHasher(memory_cost=1024, time_cost=3, parallelism=4)  # ruleid: argon2-params
strong = PasswordHasher(memory_cost=65536, time_cost=3, parallelism=4)  # ok: argon2-params


# --- audit-write-required (SR-112) ----------------------------------------
@router.post("/accounts")  # ruleid: audit-write-required
async def create_bad(body):
    return await svc.create(body)


@router.post("/accounts/archive")  # ok: audit-write-required
async def archive_ok(body):
    await _audit("account.archive")
    return await svc.archive(body)


@router.get("/accounts")  # ok: audit-write-required
async def list_ok():
    return await svc.list()
