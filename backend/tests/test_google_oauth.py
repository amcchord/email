from datetime import datetime, timezone
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from starlette.responses import Response

from backend.routers import accounts, auth
from backend.services.google_oauth import build_google_flow, new_code_verifier
from backend.utils.security import encrypt_value, verify_oauth_state


class ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeSession:
    def __init__(self, *results):
        self.results = list(results)
        self.committed = False
        self.rolled_back = False
        self.added = []

    async def execute(self, _statement):
        if not self.results:
            raise AssertionError("Unexpected database query")
        return ScalarResult(self.results.pop(0))

    async def commit(self):
        self.committed = True

    async def rollback(self):
        self.rolled_back = True

    def add(self, value):
        self.added.append(value)

    async def flush(self):
        return None

class BoundAccountSession(FakeSession):
    """Return the target only when the query is bound to its id and owner."""

    def __init__(self, user, target, decoy, calendar_health):
        super().__init__()
        self.user = user
        self.target = target
        self.decoy = decoy
        self.calendar_health = calendar_health
        self.call_count = 0
        self.account_query_params = {}

    async def execute(self, statement):
        self.call_count += 1
        if self.call_count == 1:
            return ScalarResult(self.user)
        if self.call_count == 2:
            self.account_query_params = statement.compile().params
            values = set(self.account_query_params.values())
            selected = (
                self.target
                if self.target.id in values and self.target.user_id in values
                else self.decoy
            )
            return ScalarResult(selected)
        if self.call_count == 3:
            return ScalarResult(self.calendar_health)
        raise AssertionError("Unexpected database query")


def request_with_nonce(nonce):
    return SimpleNamespace(cookies={accounts.ACCOUNT_OAUTH_NONCE_COOKIE: nonce})


def redirect_query(response):
    return parse_qs(urlparse(response.headers["location"]).query)


def generated_state(*, account_id=41, return_page="calendar"):
    verifier = "generated-verifier-" + "v" * 48
    nonce = "generated-nonce"
    state = accounts._account_oauth_state(
        7,
        verifier,
        nonce=nonce,
        account_id=account_id,
        return_page=return_page,
    )
    return state, verifier, nonce


def test_google_flow_reuses_explicit_pkce_verifier_across_requests():
    verifier = new_code_verifier()
    start_flow = build_google_flow(
        "generated-client",
        "generated-secret",
        "https://mail.example.test/api/accounts/oauth/callback",
        accounts.GMAIL_SCOPES,
        code_verifier=verifier,
    )
    auth_url, _ = start_flow.authorization_url(state="generated-state")
    query = parse_qs(urlparse(auth_url).query)

    callback_flow = build_google_flow(
        "generated-client",
        "generated-secret",
        "https://mail.example.test/api/accounts/oauth/callback",
        accounts.GMAIL_SCOPES,
        code_verifier=verifier,
    )

    assert 43 <= len(verifier) <= 128
    assert query["code_challenge_method"] == ["S256"]
    assert query["code_challenge"]
    assert start_flow.code_verifier == verifier
    assert callback_flow.code_verifier == verifier


def test_account_oauth_state_binds_verifier_nonce_account_and_return_page():
    state, verifier, nonce = generated_state()
    payload = verify_oauth_state(state)

    assert payload["user_id"] == 7
    assert payload["account_id"] == 41
    assert payload["return_page"] == "calendar"
    assert payload["nonce"] == nonce
    assert accounts._restore_account_code_verifier(payload) == verifier
    assert verifier not in state


@pytest.mark.asyncio
async def test_google_login_start_sets_state_and_encrypted_verifier_cookies(monkeypatch):
    observed = {}

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class Flow:
        def authorization_url(self, **kwargs):
            observed["state"] = kwargs["state"]
            return "https://accounts.example.test/generated", kwargs["state"]

    def fake_flow(*_args, code_verifier, **_kwargs):
        observed["verifier"] = code_verifier
        return Flow()

    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(auth, "new_code_verifier", lambda: "generated-login-verifier")
    monkeypatch.setattr(auth, "build_google_flow", fake_flow)

    response = await auth.google_login_start(Response(), db=FakeSession())
    cookies = response.headers.getlist("set-cookie")

    assert observed["verifier"] == "generated-login-verifier"
    assert observed["state"]
    assert any(cookie.startswith(f"{auth.GOOGLE_LOGIN_STATE_COOKIE}=") for cookie in cookies)
    verifier_cookie = next(
        cookie for cookie in cookies
        if cookie.startswith(f"{auth.GOOGLE_LOGIN_VERIFIER_COOKIE}=")
    )
    assert "generated-login-verifier" not in verifier_cookie
    assert "HttpOnly" in verifier_cookie


@pytest.mark.asyncio
async def test_cancelled_google_login_redirects_instead_of_returning_422():
    response = await auth.google_login_callback(
        code="",
        state="generated-state",
        error="access_denied",
        request=SimpleNamespace(cookies={auth.GOOGLE_LOGIN_STATE_COOKIE: "generated-state"}),
        db=FakeSession(),
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?login_error=access_denied"


@pytest.mark.asyncio
async def test_google_login_setup_failure_rolls_back_without_logging_oauth_values(
    monkeypatch,
    caplog,
):
    state = "generated-login-state"
    verifier = "generated-login-verifier"
    session = FakeSession()

    async def failed_credentials(_db):
        raise RuntimeError("generated login setup detail")

    monkeypatch.setattr(
        "backend.services.credentials.get_google_credentials",
        failed_credentials,
    )
    caplog.set_level("ERROR", logger=auth.__name__)

    response = await auth.google_login_callback(
        code="generated-login-code",
        state=state,
        request=SimpleNamespace(
            cookies={
                auth.GOOGLE_LOGIN_STATE_COOKIE: state,
                auth.GOOGLE_LOGIN_VERIFIER_COOKIE: encrypt_value(verifier),
            }
        ),
        db=session,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?login_error=configuration_error"
    assert session.rolled_back is True
    assert "RuntimeError" in caplog.text
    for sensitive in (state, verifier, "generated-login-code", "login setup detail"):
        assert sensitive not in response.headers["location"]
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_google_login_malformed_profile_redirects_instead_of_raw_500(monkeypatch):
    state = "generated-login-state"
    session = FakeSession()
    credentials = SimpleNamespace(token="generated-access", refresh_token=None)

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(execute=lambda: ["not", "an", "object"])
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))
    monkeypatch.setattr(
        "backend.services.credentials.get_google_credentials",
        fake_credentials,
    )
    monkeypatch.setattr(auth, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)

    response = await auth.google_login_callback(
        code="generated-login-code",
        state=state,
        request=SimpleNamespace(
            cookies={
                auth.GOOGLE_LOGIN_STATE_COOKIE: state,
                auth.GOOGLE_LOGIN_VERIFIER_COOKIE: encrypt_value("generated-verifier"),
            }
        ),
        db=session,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?login_error=profile_lookup_failed"
    assert session.rolled_back is True


@pytest.mark.asyncio
async def test_google_login_persistence_failure_rolls_back_and_redacts_logs(
    monkeypatch,
    caplog,
):
    state = "generated-login-state"
    verifier = "generated-login-verifier"
    user = SimpleNamespace(
        id=23,
        display_name="Old Name",
        avatar_url=None,
    )

    class CommitFailureSession(FakeSession):
        async def commit(self):
            raise RuntimeError("generated persistence email@example.test detail")

    session = CommitFailureSession(user)
    credentials = SimpleNamespace(token="generated-access", refresh_token=None)

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    async def allow_generated_user(_email, _db):
        return True

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(
        execute=lambda: {
            "email": "generated-user@example.test",
            "name": "Generated User",
            "picture": "https://images.example.test/generated",
        }
    )
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))
    monkeypatch.setattr(
        "backend.services.credentials.get_google_credentials",
        fake_credentials,
    )
    monkeypatch.setattr(auth, "_check_allowed", allow_generated_user)
    monkeypatch.setattr(auth, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)
    caplog.set_level("ERROR", logger=auth.__name__)

    response = await auth.google_login_callback(
        code="generated-login-code",
        state=state,
        request=SimpleNamespace(
            cookies={
                auth.GOOGLE_LOGIN_STATE_COOKIE: state,
                auth.GOOGLE_LOGIN_VERIFIER_COOKIE: encrypt_value(verifier),
            }
        ),
        db=session,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?login_error=account_update_failed"
    assert session.rolled_back is True
    assert session.committed is False
    assert "RuntimeError" in caplog.text
    for sensitive in (
        state,
        verifier,
        "generated-login-code",
        "generated-user@example.test",
        "persistence email@example.test detail",
    ):
        assert sensitive not in response.headers["location"]
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_google_login_cookie_failure_rolls_back_before_commit(monkeypatch, caplog):
    state = "generated-login-state"
    user = SimpleNamespace(id=23, display_name="Old Name", avatar_url=None)
    session = FakeSession(user)
    credentials = SimpleNamespace(token="generated-access", refresh_token=None)

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    async def allow_generated_user(_email, _db):
        return True

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(execute=lambda: {
        "email": "generated-user@example.test",
        "name": "Generated User",
    })
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))

    def fail_cookie_write(*_args, **_kwargs):
        raise RuntimeError("generated cookie detail")

    monkeypatch.setattr(
        "backend.services.credentials.get_google_credentials",
        fake_credentials,
    )
    monkeypatch.setattr(auth, "_check_allowed", allow_generated_user)
    monkeypatch.setattr(auth, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)
    monkeypatch.setattr(auth, "_set_auth_cookies", fail_cookie_write)
    caplog.set_level("ERROR", logger=auth.__name__)

    response = await auth.google_login_callback(
        code="generated-login-code",
        state=state,
        request=SimpleNamespace(
            cookies={
                auth.GOOGLE_LOGIN_STATE_COOKIE: state,
                auth.GOOGLE_LOGIN_VERIFIER_COOKIE: encrypt_value("generated-verifier"),
            }
        ),
        db=session,
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/?login_error=authorization_failed"
    assert session.rolled_back is True
    assert session.committed is False
    assert "RuntimeError" in caplog.text
    for sensitive in (
        state,
        "generated-login-code",
        "generated-user@example.test",
        "generated cookie detail",
    ):
        assert sensitive not in response.headers["location"]
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_cancelled_account_oauth_returns_safe_calendar_redirect(monkeypatch):
    state, _, nonce = generated_state()
    session = FakeSession(SimpleNamespace(id=7, is_active=True))

    response = await accounts.oauth_callback(
        code="",
        state=state,
        error="access_denied",
        request=request_with_nonce(nonce),
        db=session,
    )

    assert response.status_code == 303
    assert redirect_query(response) == {
        "page": ["calendar"],
        "oauth_error": ["access_denied"],
    }
    assert "generated" not in response.headers["location"]
    assert session.committed is False


@pytest.mark.asyncio
async def test_token_exchange_failure_redirects_without_exposing_oauth_values(monkeypatch):
    state, verifier, nonce = generated_state()
    session = FakeSession(SimpleNamespace(id=7, is_active=True))
    observed = {}

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class FailedFlow:
        def fetch_token(self, *, code):
            observed["code"] = code
            raise RuntimeError("generated provider detail that must not reach the URL")

    def fake_flow(*_args, code_verifier, **_kwargs):
        observed["verifier"] = code_verifier
        return FailedFlow()

    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "build_google_flow", fake_flow)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert observed == {"code": "generated-oauth-code", "verifier": verifier}
    assert response.status_code == 303
    assert redirect_query(response)["oauth_error"] == ["token_exchange_failed"]
    assert "generated-oauth-code" not in response.headers["location"]
    assert "provider" not in response.headers["location"]
    assert session.committed is False


@pytest.mark.asyncio
async def test_account_oauth_rejects_mismatched_nonce_before_any_database_read():
    state, _, _ = generated_state()
    session = FakeSession()

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce("different-generated-nonce"),
        db=session,
    )

    assert redirect_query(response)["oauth_error"] == ["invalid_state"]
    assert session.results == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_legacy_account_oauth_state_redirects_safely_without_provider_calls():
    """An authorization started before the PKCE rollout must never raw-500."""
    legacy_state = accounts.sign_oauth_state({"user_id": 7})
    session = FakeSession()

    response = await accounts.oauth_callback(
        code="generated-legacy-oauth-code",
        state=legacy_state,
        request=SimpleNamespace(cookies={}),
        db=session,
    )

    assert response.status_code == 303
    assert redirect_query(response) == {
        "page": ["admin"],
        "tab": ["profile"],
        "oauth_error": ["invalid_state"],
    }
    assert "generated-legacy-oauth-code" not in response.headers["location"]
    assert session.results == []
    assert session.committed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "state_data",
    [
        [],
        {
            "user_id": "7",
            "account_id": 41,
            "nonce": "generated-nonce",
            "pkce": "generated-encrypted-verifier",
            "return_page": "calendar",
        },
        {
            "user_id": 7,
            "account_id": "41",
            "nonce": "generated-nonce",
            "pkce": "generated-encrypted-verifier",
            "return_page": "calendar",
        },
        {
            "user_id": 7,
            "account_id": 41,
            "nonce": 123,
            "pkce": "generated-encrypted-verifier",
            "return_page": "calendar",
        },
    ],
)
async def test_account_callback_rejects_mistyped_signed_state_before_database_read(
    monkeypatch,
    state_data,
):
    session = FakeSession()
    monkeypatch.setattr(accounts, "verify_oauth_state", lambda _state: state_data)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state="generated-signed-state",
        request=request_with_nonce("generated-nonce"),
        db=session,
    )

    assert response.status_code == 303
    assert redirect_query(response)["oauth_error"] == ["invalid_state"]
    assert session.results == []
    assert session.committed is False


@pytest.mark.asyncio
async def test_account_callback_database_failure_rolls_back_and_redirects_safely(caplog):
    state, verifier, nonce = generated_state()

    class ReadFailureSession(FakeSession):
        async def execute(self, _statement):
            raise RuntimeError("generated database detail")

    session = ReadFailureSession()
    caplog.set_level("ERROR", logger=accounts.__name__)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert response.status_code == 303
    assert redirect_query(response)["oauth_error"] == ["account_update_failed"]
    assert session.rolled_back is True
    assert "user_id=7" in caplog.text
    assert "RuntimeError" in caplog.text
    for sensitive in (
        "generated-oauth-code",
        state,
        verifier,
        "generated database detail",
    ):
        assert sensitive not in response.headers["location"]
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_account_callback_setup_failure_uses_configuration_redirect(monkeypatch, caplog):
    state, verifier, nonce = generated_state()
    session = FakeSession(SimpleNamespace(id=7, is_active=True))

    async def failed_credentials(_db):
        raise RuntimeError("generated setup provider detail")

    monkeypatch.setattr(
        "backend.services.credentials.get_google_credentials",
        failed_credentials,
    )
    caplog.set_level("ERROR", logger=accounts.__name__)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert redirect_query(response)["oauth_error"] == ["configuration_error"]
    assert session.rolled_back is True
    for sensitive in (
        "generated-oauth-code",
        state,
        verifier,
        "setup provider detail",
    ):
        assert sensitive not in response.headers["location"]
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_successful_calendar_reauth_updates_only_bound_account(monkeypatch):
    state, verifier, nonce = generated_state()
    stored_refresh = encrypt_value("known-refresh")
    account = SimpleNamespace(
        id=41,
        user_id=7,
        email="calendar-owner@example.test",
        encrypted_access_token="old-access",
        encrypted_refresh_token=stored_refresh,
        token_expiry=None,
        scopes="[]",
        is_active=False,
    )
    decoy = SimpleNamespace(
        id=99,
        user_id=8,
        email="other-account@example.test",
        encrypted_access_token="decoy-access",
        encrypted_refresh_token=encrypt_value("decoy-refresh"),
        token_expiry=None,
        scopes="[]",
        is_active=False,
    )
    calendar_health = SimpleNamespace(status="error", error_message="expired", needs_reauth=True)
    session = BoundAccountSession(
        SimpleNamespace(id=7, is_active=True),
        account,
        decoy,
        calendar_health,
    )
    credentials = SimpleNamespace(
        token="generated-access",
        refresh_token=None,
        expiry=datetime(2026, 8, 30, 13, 30, tzinfo=timezone.utc),
        granted_scopes=list(accounts.GMAIL_SCOPES),
        scopes=list(accounts.GMAIL_SCOPES),
    )

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    async def allow_generated_account(_email, _db):
        return True

    class SuccessfulFlow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, *, code):
            assert code == "generated-oauth-code"

    class UserInfoRequest:
        def execute(self):
            return {"email": "calendar-owner@example.test", "name": "Generated Owner"}

    service = SimpleNamespace(
        userinfo=lambda: SimpleNamespace(get=lambda: UserInfoRequest())
    )

    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "_check_allowed", allow_generated_account)
    monkeypatch.setattr(
        accounts,
        "build_google_flow",
        lambda *_args, code_verifier, **_kwargs: (
            SuccessfulFlow() if code_verifier == verifier else pytest.fail("wrong verifier")
        ),
    )
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert response.status_code == 303
    assert redirect_query(response) == {
        "page": ["calendar"],
        "oauth": ["reauthorized"],
    }
    assert session.committed is True
    assert account.encrypted_refresh_token == stored_refresh
    assert account.is_active is True
    assert set(__import__("json").loads(account.scopes)) == set(accounts.GMAIL_SCOPES)
    assert calendar_health.status == "idle"
    assert calendar_health.error_message is None
    assert calendar_health.needs_reauth is False
    assert 41 in set(session.account_query_params.values())
    assert 7 in set(session.account_query_params.values())
    assert decoy.encrypted_access_token == "decoy-access"
    assert decoy.is_active is False


@pytest.mark.asyncio
async def test_reauth_rejects_wrong_google_identity_without_mutation(monkeypatch):
    state, _, nonce = generated_state()
    account = SimpleNamespace(
        id=41,
        user_id=7,
        email="calendar-owner@example.test",
        encrypted_access_token="unchanged",
        encrypted_refresh_token=encrypt_value("known-refresh"),
        token_expiry=None,
        scopes="[]",
        is_active=False,
    )
    session = FakeSession(SimpleNamespace(id=7, is_active=True), account)
    credentials = SimpleNamespace(
        token="generated-access",
        refresh_token="generated-refresh",
        expiry=None,
        granted_scopes=list(accounts.GMAIL_SCOPES),
        scopes=list(accounts.GMAIL_SCOPES),
    )

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    async def allow_generated_account(_email, _db):
        return True

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(execute=lambda: {"email": "different@example.test"})
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))

    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "_check_allowed", allow_generated_account)
    monkeypatch.setattr(accounts, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert redirect_query(response)["oauth_error"] == ["account_mismatch"]
    assert account.encrypted_access_token == "unchanged"
    assert account.is_active is False
    assert session.committed is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("granted_scopes", "stored_refresh", "expected_error"),
    [
        (
            [scope for scope in accounts.GMAIL_SCOPES if "calendar.readonly" not in scope],
            encrypt_value("known-refresh"),
            "calendar_scope_missing",
        ),
        (
            [scope for scope in accounts.GMAIL_SCOPES if "gmail.send" not in scope],
            encrypt_value("known-refresh"),
            "required_scopes_missing",
        ),
        (list(accounts.GMAIL_SCOPES), "", "refresh_token_missing"),
    ],
)
async def test_reauth_fails_closed_without_calendar_scope_or_durable_refresh(
    monkeypatch,
    granted_scopes,
    stored_refresh,
    expected_error,
):
    state, _, nonce = generated_state()
    account = SimpleNamespace(
        id=41,
        user_id=7,
        email="calendar-owner@example.test",
        encrypted_access_token="unchanged",
        encrypted_refresh_token=stored_refresh,
        token_expiry=None,
        scopes="[]",
        is_active=False,
    )
    results = [SimpleNamespace(id=7, is_active=True)]
    if expected_error == "refresh_token_missing":
        results.append(account)
    session = FakeSession(*results)
    credentials = SimpleNamespace(
        token="generated-access",
        refresh_token=None,
        expiry=None,
        granted_scopes=granted_scopes,
        scopes=list(accounts.GMAIL_SCOPES),
    )

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    async def allow_generated_account(_email, _db):
        return True

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(execute=lambda: {
        "email": "calendar-owner@example.test",
        "name": "Generated Owner",
    })
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))

    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "_check_allowed", allow_generated_account)
    monkeypatch.setattr(accounts, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert redirect_query(response)["oauth_error"] == [expected_error]
    assert account.encrypted_access_token == "unchanged"
    assert account.is_active is False
    assert session.committed is False


@pytest.mark.asyncio
async def test_profile_lookup_failure_redirects_without_secrets_or_commit(monkeypatch, caplog):
    state, verifier, nonce = generated_state()
    session = FakeSession(SimpleNamespace(id=7, is_active=True))
    credentials = SimpleNamespace(token="generated-access", refresh_token="generated-refresh")

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    class FailedProfileRequest:
        def execute(self):
            raise RuntimeError("generated provider profile detail")

    service = SimpleNamespace(
        userinfo=lambda: SimpleNamespace(get=lambda: FailedProfileRequest())
    )
    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)
    caplog.set_level("WARNING", logger=accounts.__name__)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    location = response.headers["location"]
    assert response.status_code == 303
    assert redirect_query(response)["oauth_error"] == ["profile_lookup_failed"]
    assert session.committed is False
    for sensitive in ("generated-oauth-code", state, verifier, "provider profile detail"):
        assert sensitive not in location
        assert sensitive not in caplog.text


@pytest.mark.asyncio
async def test_profile_without_email_returns_safe_redirect(monkeypatch):
    state, _, nonce = generated_state()
    session = FakeSession(SimpleNamespace(id=7, is_active=True))
    credentials = SimpleNamespace(token="generated-access", refresh_token="generated-refresh")

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(execute=lambda: {})
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))
    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    assert response.status_code == 303
    assert redirect_query(response)["oauth_error"] == ["no_email"]
    assert session.committed is False


@pytest.mark.asyncio
async def test_new_account_flush_failure_rolls_back_without_logging_secrets(monkeypatch, caplog):
    state, verifier, nonce = generated_state(account_id=None, return_page="admin")

    class FlushFailureSession(FakeSession):
        async def flush(self):
            raise RuntimeError("generated token and provider detail")

    session = FlushFailureSession(SimpleNamespace(id=7, is_active=True), None)
    credentials = SimpleNamespace(
        token="generated-sensitive-access",
        refresh_token="generated-sensitive-refresh",
        expiry=None,
        granted_scopes=list(accounts.GMAIL_SCOPES),
        scopes=list(accounts.GMAIL_SCOPES),
    )

    async def fake_credentials(_db):
        return "generated-client", "generated-secret"

    async def allow_generated_account(_email, _db):
        return True

    class Flow:
        def __init__(self):
            self.credentials = credentials

        def fetch_token(self, **_kwargs):
            return None

    request = SimpleNamespace(execute=lambda: {
        "email": "new-account@example.test",
        "name": "Generated Owner",
    })
    service = SimpleNamespace(userinfo=lambda: SimpleNamespace(get=lambda: request))
    monkeypatch.setattr("backend.services.credentials.get_google_credentials", fake_credentials)
    monkeypatch.setattr(accounts, "_check_allowed", allow_generated_account)
    monkeypatch.setattr(accounts, "build_google_flow", lambda *_args, **_kwargs: Flow())
    monkeypatch.setattr("googleapiclient.discovery.build", lambda *_args, **_kwargs: service)
    caplog.set_level("ERROR", logger=accounts.__name__)

    response = await accounts.oauth_callback(
        code="generated-oauth-code",
        state=state,
        request=request_with_nonce(nonce),
        db=session,
    )

    location = response.headers["location"]
    assert response.status_code == 303
    assert redirect_query(response)["oauth_error"] == ["account_update_failed"]
    assert session.rolled_back is True
    assert session.committed is False
    for sensitive in (
        "generated-oauth-code",
        state,
        verifier,
        "generated-sensitive-access",
        "generated-sensitive-refresh",
        "new-account@example.test",
        "provider detail",
    ):
        assert sensitive not in location
        assert sensitive not in caplog.text
