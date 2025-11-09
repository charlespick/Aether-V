import base64
import json
import time
from datetime import datetime
from types import SimpleNamespace

import pytest
from authlib.jose import JsonWebKey, jwt
from fastapi import HTTPException, status

from app.core import auth


@pytest.fixture(autouse=True)
def restore_jwks_cache():
    """Ensure jwks_cache global is restored after each test."""

    original = auth.jwks_cache
    yield
    auth.jwks_cache = original


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_split_config_values_handles_multiple_separators():
    result = auth._split_config_values("alpha, beta gamma;delta")
    assert result == ["alpha", "beta", "gamma", "delta"]


def test_split_config_values_handles_empty_input():
    assert auth._split_config_values(None) == []


def test_normalize_claim_values_adds_variations():
    values = auth._normalize_claim_values(["PREFIX/Reader", "api://Writer"])
    assert values == {"prefix/reader", "reader", "api://writer", "//writer", "writer"}


def test_extract_scope_claims_prefers_strings():
    claims = {"scp": "read write", "scope": "admin"}
    assert sorted(auth._extract_scope_claims(claims)) == ["admin", "read", "write"]


class DummyResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")

    def json(self):
        return self._payload


class DummyAsyncClient:
    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        payload = self._responses.pop(0)
        if isinstance(payload, Exception):
            raise payload
        return DummyResponse(payload)


@pytest.mark.anyio("asyncio")
async def test_jwks_cache_fetches_and_caches(monkeypatch):
    payload = {"keys": [{"kty": "RSA", "use": "sig", "kid": "1"}]}
    calls = []

    def factory(*args, **kwargs):
        calls.append(1)
        return DummyAsyncClient([payload])

    monkeypatch.setattr(auth.httpx, "AsyncClient", factory)
    cache = auth.JWKSCache("https://example.com/jwks", ttl=300)

    first = await cache.get_keys()
    second = await cache.get_keys()

    assert first == second == payload
    assert len(calls) == 1, "Second call should reuse cached JWKS"


@pytest.mark.anyio("asyncio")
async def test_jwks_cache_returns_stale_on_fetch_error(monkeypatch):
    payload = {"keys": [{"kty": "RSA", "use": "sig", "kid": "1"}]}

    def factory(*args, **kwargs):
        return DummyAsyncClient([payload, RuntimeError("boom")])

    monkeypatch.setattr(auth.httpx, "AsyncClient", factory)
    cache = auth.JWKSCache("https://example.com/jwks", ttl=300)

    cached = await cache.get_keys()
    assert cached == payload

    reused = await cache.get_keys()
    assert reused == payload


@pytest.mark.anyio("asyncio")
async def test_jwks_cache_errors_when_unavailable(monkeypatch):
    def factory(*args, **kwargs):
        return DummyAsyncClient([RuntimeError("boom")])

    monkeypatch.setattr(auth.httpx, "AsyncClient", factory)
    cache = auth.JWKSCache("https://example.com/jwks", ttl=300)

    with pytest.raises(auth.HTTPException) as exc:
        await cache.get_keys()

    assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


@pytest.mark.anyio("asyncio")
async def test_jwks_cache_force_refresh(monkeypatch):
    first_payload = {"keys": [{"kty": "RSA", "use": "sig", "kid": "1"}]}
    refreshed_payload = {"keys": [{"kty": "RSA", "use": "sig", "kid": "2"}]}

    responses = [first_payload, refreshed_payload]

    def factory(*args, **kwargs):
        return DummyAsyncClient(responses)

    monkeypatch.setattr(auth.httpx, "AsyncClient", factory)
    cache = auth.JWKSCache("https://example.com/jwks", ttl=300)

    await cache.get_keys()
    refreshed = await cache.force_refresh()
    assert refreshed == refreshed_payload


def test_discover_oidc_metadata(monkeypatch):
    class Dummy:
        def raise_for_status(self):
            pass

        def json(self):
            return {"issuer": "https://issuer"}

    monkeypatch.setattr(auth.httpx, "get", lambda url, timeout=5.0: Dummy())
    metadata = auth.discover_oidc_metadata("https://issuer")
    assert metadata["issuer"] == "https://issuer"


def test_discover_oidc_metadata_errors(monkeypatch):
    auth.discover_oidc_metadata.cache_clear()

    def raising(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(auth.httpx, "get", raising)

    with pytest.raises(RuntimeError):
        auth.discover_oidc_metadata("https://issuer")


def _encode_segment(data):
    raw = json.dumps(data).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def test_jwt_header_payload_unverified():
    header = {"alg": "RS256"}
    payload = {"sub": "user"}
    token = f"{_encode_segment(header)}.{_encode_segment(payload)}.signature"

    assert auth.jwt_header_unverified(token) == header
    assert auth.jwt_payload_unverified(token) == payload


def test_analyze_token_type_identifies_tokens(monkeypatch):
    monkeypatch.setattr(auth.settings, "oidc_client_id", "client")

    id_payload = {"nonce": "n", "aud": "client"}
    access_payload = {"scp": "read write"}
    unknown_payload = {"iss": "issuer"}

    id_token = f"h.{_encode_segment(id_payload)}.s"
    access_token = f"h.{_encode_segment(access_payload)}.s"
    unknown_token = f"h.{_encode_segment(unknown_payload)}.s"

    assert auth.analyze_token_type(id_token) == "id_token"
    assert auth.analyze_token_type(access_token) == "access_token"
    assert auth.analyze_token_type(unknown_token) == "unknown"


def test_extract_user_roles_aggregates_claims():
    claims = {
        "roles": ["RoleA"],
        "groups": ["GroupB"],
        "wids": ["WidC"],
        "app_roles": ["AppRole"],
        "scope": "one two",
    }
    roles = auth.extract_user_roles(claims)
    assert sorted(roles) == ["AppRole", "GroupB", "RoleA", "WidC", "one", "two"]


def test_determine_identity_type():
    assert auth.determine_identity_type({"idtyp": "app"}) == "service_principal"
    assert auth.determine_identity_type({"appid": "x"}) == "service_principal"
    assert auth.determine_identity_type({"preferred_username": "user"}) == "user"


def test_determine_permissions_with_hierarchy(monkeypatch):
    monkeypatch.setattr(auth.settings, "oidc_reader_permissions", "reader-role")
    monkeypatch.setattr(auth.settings, "oidc_writer_permissions", "writer-role")
    monkeypatch.setattr(auth.settings, "oidc_admin_permissions", "admin-role")
    monkeypatch.setattr(auth.settings, "oidc_role_name", None)

    claims = {"roles": ["admin-role"]}
    perms = auth.determine_permissions(claims)
    assert perms == {auth.Permission.ADMIN, auth.Permission.WRITER, auth.Permission.READER}


def test_determine_permissions_with_legacy_fallback(monkeypatch):
    monkeypatch.setattr(auth.settings, "oidc_reader_permissions", "reader-role")
    monkeypatch.setattr(auth.settings, "oidc_writer_permissions", "writer-role")
    monkeypatch.setattr(auth.settings, "oidc_admin_permissions", "admin-role")
    monkeypatch.setattr(auth.settings, "oidc_role_name", "legacy-role")

    claims = {"roles": ["legacy-role"]}
    perms = auth.determine_permissions(claims)
    assert perms == {auth.Permission.WRITER, auth.Permission.READER}


def test_enrich_identity_includes_metadata(monkeypatch):
    monkeypatch.setattr(auth.settings, "oidc_reader_permissions", "reader")
    monkeypatch.setattr(auth.settings, "oidc_writer_permissions", "writer")
    monkeypatch.setattr(auth.settings, "oidc_admin_permissions", "admin")

    claims = {"roles": ["admin"], "preferred_username": "user@example.com"}
    enriched = auth.enrich_identity(claims)
    assert enriched["identity_type"] == "user"
    assert enriched["permissions"] == ["admin", "reader", "writer"]


def _build_signed_token(monkeypatch, *, audiences=None, extra_claims=None):
    key = JsonWebKey.generate_key("RSA", 2048, options={"kid": "kid"}, is_private=True)
    public_jwk = key.as_dict(is_private=False)

    class StaticJWKS:
        async def get_keys(self):
            return {"keys": [public_jwk]}

        async def force_refresh(self):
            return await self.get_keys()

    auth.jwks_cache = StaticJWKS()

    now = int(time.time())
    payload = {
        "sub": "user",
        "iss": "https://issuer",
        "aud": audiences or "api://client",
        "exp": now + 3600,
        "iat": now,
    }
    if extra_claims:
        payload.update(extra_claims)

    header = {"alg": "RS256", "kid": "kid", "typ": "JWT"}
    token = jwt.encode(header, payload, key).decode()

    monkeypatch.setattr(auth.settings, "oidc_issuer_url", "https://issuer")
    monkeypatch.setattr(auth.settings, "oidc_client_id", "client")
    monkeypatch.setattr(auth.settings, "oidc_api_audience", "api://client")
    monkeypatch.setattr(auth.settings, "max_token_age", 7200)

    return token, payload


@pytest.mark.anyio("asyncio")
async def test_validate_oidc_token_success(monkeypatch):
    token, payload = _build_signed_token(monkeypatch, extra_claims={"scp": "read"})
    claims = await auth.validate_oidc_token(token)
    for key in ["sub", "iss", "aud", "exp"]:
        assert claims[key] == payload[key]


@pytest.mark.anyio("asyncio")
async def test_validate_oidc_token_invalid_issuer(monkeypatch):
    token, _ = _build_signed_token(monkeypatch)
    monkeypatch.setattr(auth.settings, "oidc_issuer_url", "https://other")

    with pytest.raises(auth.JoseError):
        await auth.validate_oidc_token(token)


@pytest.mark.anyio("asyncio")
async def test_validate_oidc_token_invalid_audience(monkeypatch):
    token, _ = _build_signed_token(monkeypatch, audiences="wrong")

    with pytest.raises(auth.JoseError):
        await auth.validate_oidc_token(token)


@pytest.mark.anyio("asyncio")
async def test_authenticate_with_token_returns_enriched_identity(monkeypatch):
    token, _ = _build_signed_token(monkeypatch, extra_claims={"roles": ["Aether.Admin"]})
    monkeypatch.setattr(auth.settings, "oidc_reader_permissions", "Aether.Reader")
    monkeypatch.setattr(auth.settings, "oidc_writer_permissions", "Aether.Writer")
    monkeypatch.setattr(auth.settings, "oidc_admin_permissions", "Aether.Admin")

    user = await auth.authenticate_with_token(token, client_ip="1.2.3.4")
    assert user["auth_type"] == "oidc_user"
    assert set(user["permissions"]) == {"admin", "reader", "writer"}


@pytest.mark.anyio("asyncio")
async def test_authenticate_with_token_requires_permissions(monkeypatch):
    token, _ = _build_signed_token(monkeypatch)
    monkeypatch.setattr(auth.settings, "oidc_reader_permissions", "reader")
    monkeypatch.setattr(auth.settings, "oidc_writer_permissions", "writer")
    monkeypatch.setattr(auth.settings, "oidc_admin_permissions", "admin")

    with pytest.raises(HTTPException) as exc:
        await auth.authenticate_with_token(token)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_validate_session_data_recent_session():
    session = {
        "authenticated": True,
        "auth_timestamp": datetime.now().isoformat(),
        "permissions": ["reader"],
        "preferred_username": "user",
    }
    user = auth.validate_session_data(session, client_ip="1.2.3.4")
    assert user["auth_type"] == "session"


def test_validate_session_data_requires_permissions():
    session = {
        "authenticated": True,
        "auth_timestamp": datetime.now().isoformat(),
        "permissions": [],
    }
    assert auth.validate_session_data(session) is None


def test_validate_session_data_legacy_without_timestamp():
    session = {
        "authenticated": True,
        "permissions": ["writer"],
        "preferred_username": "legacy",
    }
    user = auth.validate_session_data(session)
    assert user["preferred_username"] == "legacy"


def test_has_permission_checks_hierarchy():
    user = {"permissions": ["admin"]}
    assert auth.has_permission(user, auth.Permission.READER)
    assert auth.has_permission(user, auth.Permission.WRITER)
    assert auth.has_permission(user, auth.Permission.ADMIN)


@pytest.mark.anyio("asyncio")
async def test_require_permission_allows_user(monkeypatch):
    async def fake_get_current_user(request, credentials):
        return {"permissions": ["reader", "writer"]}

    monkeypatch.setattr(auth, "get_current_user", fake_get_current_user)
    dependency = auth.require_permission(auth.Permission.WRITER)

    request = SimpleNamespace()
    credentials = SimpleNamespace()
    user = await dependency(request, credentials)
    assert user["permissions"] == ["reader", "writer"]


@pytest.mark.anyio("asyncio")
async def test_require_permission_blocks_user(monkeypatch):
    async def fake_get_current_user(request, credentials):
        return {"permissions": ["reader"]}

    monkeypatch.setattr(auth, "get_current_user", fake_get_current_user)
    dependency = auth.require_permission(auth.Permission.ADMIN)

    request = SimpleNamespace()
    credentials = SimpleNamespace()

    with pytest.raises(HTTPException) as exc:
        await dependency(request, credentials)

    assert exc.value.status_code == status.HTTP_403_FORBIDDEN


def test_get_dev_user_has_all_permissions():
    user = auth.get_dev_user()
    assert set(user["permissions"]) == {"admin", "reader", "writer"}


@pytest.mark.anyio("asyncio")
async def test_is_authenticated_validates_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_enabled", True)

    async def fake_validate(token):
        assert token == "good-token"
        return {}

    monkeypatch.setattr(auth, "validate_oidc_token", fake_validate)

    request = SimpleNamespace(headers={"Authorization": "Bearer good-token"})
    assert await auth.is_authenticated(request) is True


@pytest.mark.anyio("asyncio")
async def test_is_authenticated_rejects_bad_token(monkeypatch):
    monkeypatch.setattr(auth.settings, "auth_enabled", True)

    async def fake_validate(token):
        raise RuntimeError("bad")

    monkeypatch.setattr(auth, "validate_oidc_token", fake_validate)

    request = SimpleNamespace(headers={"Authorization": "Bearer bad-token"})
    assert await auth.is_authenticated(request) is False
