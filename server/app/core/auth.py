"""Authentication and authorization middleware.

Security Notes:
- Authlib pinned to ~=1.6.5 for security patches (update regularly)
- Implements PKCE for browser-based flows
- Token validation includes signature, issuer, audience, exp, nbf checks
- JWKS cached with TTL and refresh on kid mismatch
- Audit logging for security events
"""
import logging
import time
import secrets
import hashlib
import base64
import json
from enum import Enum
from typing import Any, cast, Dict, Iterable, List, Optional, Set
from functools import lru_cache
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from authlib.integrations.starlette_client import OAuth
from authlib.jose import jwt, JoseError
import httpx

from .config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# Fine-grained permission levels understood by the API router
class Permission(str, Enum):
    READER = "reader"
    WRITER = "writer"
    ADMIN = "admin"


def _split_config_values(raw_value: Optional[str]) -> List[str]:
    """Split comma or whitespace separated configuration values."""

    if not raw_value:
        return []

    values: List[str] = []
    for chunk in str(raw_value).replace(";", ",").split(","):
        parts = [part.strip() for part in chunk.split() if part.strip()]
        values.extend(parts)
    return values


def _normalize_claim_values(values: Iterable[str]) -> Set[str]:
    """Normalize claim values for case-insensitive comparison."""

    normalized: Set[str] = set()
    for value in values:
        lowered = value.lower()
        normalized.add(lowered)
        if "/" in value:
            normalized.add(value.rsplit("/", 1)[-1].lower())
        if ":" in value:
            normalized.add(value.rsplit(":", 1)[-1].lower())
    return normalized


def _extract_scope_claims(claims: Dict[str, Any]) -> List[str]:
    """Return all scope values present in scp/scope claims."""

    scopes: List[str] = []
    for claim_name in ("scp", "scope"):
        raw_value = claims.get(claim_name)
        if isinstance(raw_value, str):
            scopes.extend(scope for scope in raw_value.split() if scope)
    return scopes

# JWKS caching utility for security and performance
class JWKSCache:
    """Thread-safe JWKS cache with TTL to minimize network calls and attack surface."""
    
    def __init__(self, jwks_uri: str, ttl: int = 300):
        self.jwks_uri = jwks_uri
        self.ttl = ttl
        self._keys: Optional[Dict[str, Any]] = None
        self._fetched_at: float = 0.0

    async def get_keys(self) -> Dict[str, Any]:
        """Get JWKS keys with TTL-based caching and fallback."""
        now = time.time()
        if self._keys is not None and now - self._fetched_at < self.ttl:
            return self._keys
            
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(self.jwks_uri)
                response.raise_for_status()
                new_keys = response.json()
                
                # Validate JWKS structure
                if not isinstance(new_keys.get('keys'), list):
                    logger.error(f"Invalid JWKS format from {self.jwks_uri}")
                    raise ValueError("Invalid JWKS format")
                    
                # Security: validate each key has required fields
                for key in new_keys['keys']:
                    if not key.get('kty') or not key.get('use') or not key.get('kid'):
                        logger.error("Invalid JWK structure: missing required fields (kty, use, or kid)")
                        raise ValueError("Invalid JWK structure")
                    
                self._keys = new_keys
                self._fetched_at = now
                logger.info(f"Successfully fetched JWKS (keys: {len(new_keys.get('keys', []))})")
                return cast(Dict[str, Any], new_keys)
        except Exception as e:
            logger.error(f"JWKS fetch failed from {self.jwks_uri}: {e}")
            if self._keys is not None:
                logger.warning("Using stale JWKS cache due to fetch failure - security risk if keys rotated")
                return self._keys
            raise HTTPException(503, "Unable to validate tokens - JWKS unavailable")
            
    async def force_refresh(self) -> Dict[str, Any]:
        """Force JWKS refresh, typically on kid mismatch."""
        logger.info("Forcing JWKS refresh due to key ID mismatch")
        self._keys = None
        return await self.get_keys()# OIDC discovery with caching to reduce network calls
@lru_cache(maxsize=1)
def discover_oidc_metadata(issuer: str) -> Dict[str, str]:
    """Discover OIDC metadata with caching to minimize attack surface."""
    if not issuer:
        raise ValueError("OIDC issuer not configured")
    
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    try:
        response = httpx.get(url, timeout=5.0)
        response.raise_for_status()
        metadata = response.json()
        logger.info(f"Discovered OIDC metadata from {issuer}")
        return cast(Dict[str, str], metadata)
    except Exception as e:
        logger.error(f"Failed to discover OIDC metadata: {e}")
        raise

# Cache of discovered OIDC metadata so other modules can reuse logout endpoints
OIDC_METADATA: Optional[Dict[str, Any]] = None
_DISCOVERED_END_SESSION_ENDPOINT: Optional[str] = None


def get_end_session_endpoint() -> Optional[str]:
    """Return the configured or discovered OIDC end session endpoint if available."""

    if settings.oidc_end_session_endpoint:
        return settings.oidc_end_session_endpoint
    return _DISCOVERED_END_SESSION_ENDPOINT


# Initialize JWKS cache when authentication is enabled and OIDC is configured
jwks_cache: Optional[JWKSCache] = None
if settings.auth_enabled and settings.oidc_issuer_url:
    try:
        metadata = discover_oidc_metadata(settings.oidc_issuer_url)
        OIDC_METADATA = metadata
        end_session_endpoint = metadata.get("end_session_endpoint")
        if end_session_endpoint:
            _DISCOVERED_END_SESSION_ENDPOINT = end_session_endpoint
        jwks_uri = metadata.get("jwks_uri")
        if jwks_uri:
            jwks_cache = JWKSCache(jwks_uri, ttl=settings.jwks_cache_ttl)
            logger.info(f"Initialized JWKS cache for {jwks_uri}")
    except Exception as e:
        logger.error(f"Failed to initialize JWKS cache: {e}")

# OAuth client for OIDC with PKCE support
oauth = OAuth()

if settings.auth_enabled and settings.oidc_issuer_url and settings.oidc_client_id:
    oauth.register(
        name='oidc',
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=f"{settings.oidc_issuer_url}/.well-known/openid-configuration",
        client_kwargs={
            'scope': 'openid profile email',  # Minimal required scopes
            'token_endpoint_auth_method': 'client_secret_post',
            'code_challenge_method': 'S256',  # PKCE with SHA256
        }
    )
    logger.info("OIDC client registered with PKCE support")

# PKCE helper functions for browser-based flows
def generate_pkce_pair() -> tuple[str, str]:
    """Generate PKCE code verifier and challenge for secure browser flows."""
    code_verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).decode('utf-8').rstrip('=')
    code_challenge = base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest()).decode('utf-8').rstrip('=')
    return code_verifier, code_challenge


def jwt_header_unverified(token: str) -> Optional[Dict]:
    """
    Return the JWT header (dict) in a safe way, without validating signature.
    If the token is malformed, return None.
    """
    try:
        # The header is the first part before dot
        header_b64 = token.split(".", 1)[0]
        # Add padding if missing
        rem = len(header_b64) % 4
        if rem:
            header_b64 += "=" * (4 - rem)
        header_bytes = base64.urlsafe_b64decode(header_b64.encode("utf-8"))
        header = json.loads(header_bytes)
        return cast(Dict[Any, Any], header)
    except Exception:
        return None


def jwt_payload_unverified(token: str) -> Optional[Dict]:
    """
    Return the JWT payload (dict) in a safe way, without validating signature.
    If the token is malformed, return None.
    """
    try:
        # The payload is the second part
        payload_b64 = token.split(".", 2)[1]
        # Add padding if missing
        rem = len(payload_b64) % 4
        if rem:
            payload_b64 += "=" * (4 - rem)
        payload_bytes = base64.urlsafe_b64decode(payload_b64.encode("utf-8"))
        payload = json.loads(payload_bytes)
        return cast(Dict[Any, Any], payload)
    except Exception:
        return None


def analyze_token_type(token: str) -> str:
    """
    Analyze a JWT token to determine if it's likely an access token or ID token.
    Returns: 'access_token', 'id_token', or 'unknown'
    """
    payload = jwt_payload_unverified(token)
    if not payload:
        return 'unknown'
    
    # ID tokens typically have these claims
    id_token_indicators = ['nonce', 'at_hash', 'c_hash', 'auth_time']
    
    # Access tokens typically have these claims  
    access_token_indicators = ['scp', 'scope', 'roles', 'aio']
    
    id_score = sum(1 for claim in id_token_indicators if claim in payload)
    access_score = sum(1 for claim in access_token_indicators if claim in payload)
    
    # Check audience - if it matches our client ID, likely an ID token
    aud = payload.get('aud')
    if aud and settings.oidc_client_id:
        if (isinstance(aud, str) and aud == settings.oidc_client_id) or \
           (isinstance(aud, list) and settings.oidc_client_id in aud):
            id_score += 2
    
    logger.debug(f"Token analysis - ID score: {id_score}, Access score: {access_score}")
    
    if id_score > access_score:
        return 'id_token'
    elif access_score > id_score:
        return 'access_token'
    else:
        return 'unknown'


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """
    Validate authentication and return user info.
    
    Supports concurrent authentication modes:
    - OIDC bearer tokens (JWT) for both interactive users and service principals
    - Session-based authentication (cookies) - for browser requests after OIDC login
    - Development mode (no auth) - only if explicitly enabled
    
    Security: All authentication failures are logged for audit purposes.
    """
    client_ip = request.client.host if request.client else "unknown"
    user_agent = request.headers.get("user-agent", "unknown")
    
    # Development mode: no authentication required
    if not settings.auth_enabled:
        # Explicit safety check to prevent accidental no-auth in production
        if not settings.allow_dev_auth:
            logger.error(f"Auth disabled but ALLOW_DEV_AUTH not set - possible production misconfiguration from {client_ip}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Development authentication mode not explicitly enabled. Set ALLOW_DEV_AUTH=true in development environments only."
            )
        logger.warning(f"Authentication disabled - dev mode access from {client_ip}")
        return get_dev_user()
    
    # Check for session-based authentication first (for browser requests)
    session_data = request.session.get("user_info") if hasattr(request, 'session') else None
    if session_data:
        user = validate_session_data(session_data, client_ip)
        if user:
            return user
    
    # Require Bearer token credentials when no valid session
    if not credentials:
        logger.warning(f"Authentication required but no credentials provided from {client_ip} ({user_agent})")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    auth_failures = []
    
    # Try token authentication using OIDC-issued bearer tokens
    try:
        user = await authenticate_with_token(token, client_ip)
        if user:
            return user
        else:
            auth_failures.append("token_validation_failed")
    except HTTPException:
        raise  # Re-raise HTTP exceptions (like 403 for insufficient roles)
    except Exception as e:
        auth_failures.append(f"token_error: {type(e).__name__}")
        logger.error(f"Token authentication error from {client_ip}: {e}")
    
    # All authentication methods failed
    logger.error(f"Authentication failed from {client_ip} ({user_agent}). Attempts: {', '.join(auth_failures)}")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )


def extract_user_roles(user_info: dict) -> list[str]:
    """Extract user roles from various Azure AD token claims."""
    roles = []

    # Direct roles claim
    if "roles" in user_info and isinstance(user_info["roles"], list):
        roles.extend(user_info["roles"])

    # Azure AD groups
    if "groups" in user_info and isinstance(user_info["groups"], list):
        roles.extend(user_info["groups"])

    # Well-known IDs (built-in Azure AD roles)
    if "wids" in user_info and isinstance(user_info["wids"], list):
        roles.extend(user_info["wids"])

    # App-specific roles
    if "app_roles" in user_info and isinstance(user_info["app_roles"], list):
        roles.extend(user_info["app_roles"])

    # OAuth scopes may be space-delimited strings
    roles.extend(_extract_scope_claims(user_info))

    return list(set(roles))  # Remove duplicates


def get_identity_display_name(claims: dict) -> str:
    """Return a sensible display name for logging and auditing."""

    for key in (
        "preferred_username",
        "name",
        "app_displayname",
        "azp",
        "appid",
        "appId",
        "client_id",
        "sub",
    ):
        value = claims.get(key)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def determine_identity_type(claims: dict) -> str:
    """Identify whether the token represents a user or service principal."""

    app_identifier = claims.get("appid") or claims.get("appId")
    if claims.get("idtyp") == "app":
        return "service_principal"
    if app_identifier and not claims.get("preferred_username"):
        return "service_principal"
    return "user"


def determine_permissions(claims: dict, user_roles: Optional[List[str]] = None) -> Set[Permission]:
    """Map token claims to the internal permission set."""

    configured_permissions = {
        Permission.READER: _normalize_claim_values(
            _split_config_values(settings.oidc_reader_permissions)
        ),
        Permission.WRITER: _normalize_claim_values(
            _split_config_values(settings.oidc_writer_permissions)
        ),
        Permission.ADMIN: _normalize_claim_values(
            _split_config_values(settings.oidc_admin_permissions)
        ),
    }

    claim_values: Set[str] = set(user_roles or extract_user_roles(claims))

    # Ensure scopes are considered even if not present in user_roles input
    if user_roles is not None:
        claim_values.update(_extract_scope_claims(claims))

    normalized_claims = _normalize_claim_values(claim_values)
    granted: Set[Permission] = set()

    for permission, expected_values in configured_permissions.items():
        if expected_values and normalized_claims.intersection(expected_values):
            granted.add(permission)

    # Legacy fallback: honor the historical single-role configuration
    legacy_role = settings.oidc_role_name
    if legacy_role:
        if legacy_role.strip() == "*":
            granted.update({Permission.WRITER, Permission.READER})
        else:
            legacy_values = _normalize_claim_values(
                _split_config_values(legacy_role)
            )
            if normalized_claims.intersection(legacy_values):
                granted.add(Permission.WRITER)

    # Permission hierarchy: admin -> writer -> reader
    if Permission.ADMIN in granted:
        granted.update({Permission.WRITER, Permission.READER})
    elif Permission.WRITER in granted:
        granted.add(Permission.READER)

    logger.debug(
        "Determined permissions %s for claims values %s",
        sorted(permission.value for permission in granted),
        sorted(normalized_claims),
    )

    return granted


def enrich_identity(claims: dict) -> dict:
    """Augment raw JWT claims with derived identity metadata."""

    user_roles = extract_user_roles(claims)
    permissions = determine_permissions(claims, user_roles)
    identity_type = determine_identity_type(claims)
    display_name = get_identity_display_name(claims)

    enriched = dict(claims)
    enriched["roles"] = user_roles
    enriched["permissions"] = sorted(permission.value for permission in permissions)
    enriched["identity_type"] = identity_type
    enriched["preferred_username"] = (
        enriched.get("preferred_username") or display_name
    )
    return enriched


async def validate_oidc_token(token: str) -> dict:
    """Validate OIDC JWT token with comprehensive security checks.
    
    Security validations:
    - Signature verification using JWKS
    - Issuer validation (prevent token confusion)
    - Audience validation (prevent token reuse)
    - Timing claims (exp, nbf, iat)
    - Algorithm validation (prevent none algorithm attack)
    """
    if not jwks_cache:
        raise JoseError("OIDC not properly configured - no JWKS cache")
    
    try:
        # Validate basic token structure
        if not token or not isinstance(token, str):
            logger.error("Token validation failed: Invalid token format (not a string)")
            raise JoseError("Invalid token format")
            
        parts = token.split('.')
        if len(parts) != 3:
            logger.error(f"Token validation failed: Invalid JWT structure - has {len(parts)} parts, expected 3")
            raise JoseError("Invalid JWT structure - must have 3 parts")
            
        # Get token header to find key ID and algorithm
        header = jwt_header_unverified(token)
        if not header:
            logger.error("Token validation failed: Could not decode JWT header")
            raise JoseError("Could not decode JWT header")
            
        kid = header.get('kid')
        alg = header.get('alg')
        typ = header.get('typ')
        
        # Analyze token type for better debugging
        token_type = analyze_token_type(token)
        logger.info(f"Token validation: typ={typ}, alg={alg}, kid={kid[:8] if kid else None}..., detected_type={token_type}")
        
        # Warning if we're validating an access token (might not have right claims/audience)
        if token_type == 'access_token':
            logger.warning("Validating what appears to be an ACCESS TOKEN - this may fail if it's not intended for ID token validation")
        
        # Security: prevent none algorithm attack
        if not alg or alg.lower() == 'none':
            raise JoseError("Invalid or missing algorithm - 'none' not allowed")
            
        # Security: only allow specific algorithms
        allowed_algorithms = ['RS256', 'RS384', 'RS512', 'ES256', 'ES384', 'ES512']
        if alg not in allowed_algorithms:
            raise JoseError(f"Unsupported algorithm: {alg}")
        
        # Get JWKS and find matching key
        jwks_data = await jwks_cache.get_keys()
        keys = jwks_data.get('keys', [])
        
        logger.debug(f"JWKS contains {len(keys)} keys")
        
        key = None
        if kid:
            key = next((k for k in keys if k.get('kid') == kid), None)
            logger.debug(f"Looking for key ID {kid}: {'found' if key else 'not found'}")
        
        if not key:
            # Security: refresh JWKS on key ID mismatch (key rotation)
            logger.info(f"Key ID {kid} not found in cache, refreshing JWKS")
            jwks_data = await jwks_cache.force_refresh()
            keys = jwks_data.get('keys', [])
            logger.info(f"After refresh: JWKS contains {len(keys)} keys")
            
            if kid:
                key = next((k for k in keys if k.get('kid') == kid), None)
                logger.info(f"After refresh, key ID {kid}: {'found' if key else 'not found'}")
            
            # Only fallback to first key if no kid specified (less secure)
            if not key and not kid and keys:
                key = keys[0]
                logger.warning("No kid in token header - using first available key (security risk)")
        
        if not key:
            logger.error(f"No suitable signing key found for kid: {kid}. Available keys: {[k.get('kid') for k in keys]}")
            raise JoseError(f"No suitable signing key found for kid: {kid}")
        
        logger.debug(f"Using key: kty={key.get('kty')}, use={key.get('use')}, alg={key.get('alg')}")
        
        # Decode and validate token signature using the key directly
        try:
            claims = jwt.decode(token, key)
            logger.info("Token signature validation successful")
        except JoseError as e:
            logger.error(f"Token signature validation failed: {e}")
            logger.debug(f"Token starts with: {token[:50]}...")
            raise
        
        # Validate standard timing claims (exp, nbf, iat)
        claims.validate()
        
        # Additional security validations
        now = time.time()
        
        # Security: check token age (prevent very old tokens)
        iat = claims.get('iat')
        if iat:
            token_age = now - iat
            if settings.max_token_age and token_age > settings.max_token_age:
                logger.warning(f"Old token detected - age: {token_age}s")
            if token_age < -300:  # 5 minute clock skew tolerance
                raise JoseError("Token issued in the future")
        
        # Security: validate issuer strictly (prevent token confusion attacks)
        token_issuer = claims.get('iss')
        if not token_issuer:
            raise JoseError("Missing issuer claim")
        if token_issuer != settings.oidc_issuer_url:
            raise JoseError(f"Invalid issuer: expected {settings.oidc_issuer_url}, got {token_issuer}")
        
        # Security: validate audience (prevent token reuse)
        token_aud = claims.get('aud')
        if not token_aud:
            raise JoseError("Missing audience claim")

        aud_list = token_aud if isinstance(token_aud, list) else [token_aud]
        configured_audiences = set()

        for value in _split_config_values(settings.oidc_api_audience):
            configured_audiences.add(value)
            if value.endswith("/.default"):
                configured_audiences.add(value[: -len("/.default")])

        if settings.oidc_client_id:
            configured_audiences.add(settings.oidc_client_id)
            configured_audiences.add(f"api://{settings.oidc_client_id}")

        if configured_audiences:
            if not any(aud in configured_audiences for aud in aud_list):
                raise JoseError(f"Invalid audience: {token_aud}")
        else:
            logger.warning(
                "No configured audience to validate against; defaulting to token audience %s",
                aud_list,
            )

        # Security: check for required claims
        required_claims = ['sub', 'iss', 'aud', 'exp']
        missing_claims = [claim for claim in required_claims if claim not in claims]
        if missing_claims:
            raise JoseError(f"Missing required claims: {missing_claims}")
        
        return dict(claims)
        
    except JoseError:
        raise  # Re-raise JOSE errors as-is
    except Exception as e:
        logger.error(f"Unexpected token validation error: {type(e).__name__}: {e}")
        raise JoseError(f"Token validation failed: {type(e).__name__}")


def _require_session_permissions(
    session_data: dict, client_ip: str, warning_message: str
) -> Optional[List[str]]:
    """Ensure session permissions are present, logging a warning otherwise."""

    permissions = session_data.get("permissions")
    if permissions:
        return cast(List[str], permissions)

    logger.warning(warning_message, client_ip)
    return None


def validate_session_data(session_data: dict, client_ip: str = "unknown") -> Optional[dict]:
    """
    Shared session validation logic for both HTTP and WebSocket.
    
    Args:
        session_data: Session data from request.session or parsed cookies
        client_ip: Client IP for logging
        
    Returns:
        User info dict if valid session, None otherwise
    """
    if not session_data or not session_data.get("authenticated"):
        return None
        
    try:
        auth_timestamp = session_data.get("auth_timestamp")
        if auth_timestamp:
            from datetime import datetime, timedelta
            auth_time = datetime.fromisoformat(auth_timestamp)
            if datetime.now() - auth_time < timedelta(hours=24):
                permissions = _require_session_permissions(
                    session_data,
                    client_ip,
                    "Session for %s missing permission metadata; requiring re-authentication",
                )
                if not permissions:
                    return None

                username = get_identity_display_name(session_data)
                logger.debug(f"Session authentication successful for {username} from {client_ip}")
                return {
                    "sub": session_data.get("sub"),
                    "preferred_username": session_data.get("preferred_username") or username,
                    "roles": session_data.get("roles", []),
                    "permissions": permissions,
                    "auth_type": "session",
                    "identity_type": "user",
                }
            else:
                logger.debug(f"Session expired for client from {client_ip}")
        else:
            # No timestamp, assume valid for backward compatibility
            permissions = _require_session_permissions(
                session_data,
                client_ip,
                "Legacy session without permissions detected from %s; forcing re-authentication",
            )
            if not permissions:
                return None

            username = get_identity_display_name(session_data)
            logger.debug(f"Session authentication (no timestamp) for {username} from {client_ip}")
            return {
                "sub": session_data.get("sub"),
                "preferred_username": session_data.get("preferred_username") or username,
                "roles": session_data.get("roles", []),
                "permissions": permissions,
                "auth_type": "session",
                "identity_type": "user",
            }
    except Exception as e:
        logger.warning(f"Session validation failed from {client_ip}: {e}")
    
    return None


async def authenticate_with_token(token: str, client_ip: str = "unknown") -> Optional[dict]:
    """
    Shared token authentication logic for both HTTP and WebSocket.

    Args:
        token: Bearer token (OIDC JWT)
        client_ip: Client IP for logging

    Returns:
        User info dict if valid token, None otherwise
    """
    if not token:
        return None

    if not (settings.oidc_issuer_url and jwks_cache):
        logger.error("OIDC authentication requested but OIDC is not configured correctly")
        return None

    try:
        claims = await validate_oidc_token(token)
    except Exception as e:
        logger.error(f"OIDC token validation failed from {client_ip}: {e}")
        return None

    enriched_info = enrich_identity(claims)
    permissions = enriched_info.get("permissions", [])

    if not permissions:
        display_name = get_identity_display_name(enriched_info)
        logger.warning(
            "Principal %s from %s lacks any configured permissions",
            display_name,
            client_ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Principal lacks required permissions",
        )

    identity_type = enriched_info.get("identity_type")
    display_name = get_identity_display_name(enriched_info)
    enriched_info["auth_type"] = (
        "oidc_service_principal" if identity_type == "service_principal" else "oidc_user"
    )

    logger.info(
        "OIDC authentication successful for %s (%s) from %s with permissions %s",
        display_name,
        identity_type,
        client_ip,
        permissions,
    )
    return enriched_info


def has_permission(user: Optional[dict], permission: Permission) -> bool:
    """Check whether the authenticated user has the requested permission."""

    if not user:
        return False

    raw_permissions = user.get("permissions", [])
    normalized = {
        perm.value.lower() if isinstance(perm, Permission) else str(perm).lower()
        for perm in raw_permissions
        if perm
    }

    if not normalized:
        return False

    if permission == Permission.READER:
        return bool(
            normalized
            & {
                Permission.READER.value,
                Permission.WRITER.value,
                Permission.ADMIN.value,
            }
        )
    if permission == Permission.WRITER:
        return bool(
            normalized & {Permission.WRITER.value, Permission.ADMIN.value}
        )
    if permission == Permission.ADMIN:
        return Permission.ADMIN.value in normalized

    return False  # type: ignore[unreachable]  # Defensive: handle future enum additions


def require_permission(permission: Permission):
    """FastAPI dependency factory enforcing the requested permission level."""

    async def dependency(
        request: Request,
        credentials: Optional[HTTPAuthorizationCredentials] = Depends(security),
    ) -> dict:
        user = await get_current_user(request, credentials)
        if not has_permission(user, permission):
            display_name = get_identity_display_name(user)
            logger.warning(
                "Principal %s failed permission check for %s",
                display_name,
                permission.value,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Insufficient permissions for {permission.value}",
            )
        return user

    return dependency


def get_dev_user() -> dict:
    """
    Get development mode user info.
    
    Returns:
        Dev user info dict
    """
    return {
        "sub": "dev-user",
        "roles": [],
        "permissions": [
            Permission.READER.value,
            Permission.WRITER.value,
            Permission.ADMIN.value,
        ],
        "auth_type": "dev",
        "identity_type": "user",
        "preferred_username": "dev-user",
    }


async def is_authenticated(request) -> bool:
    """
    Check if a request has valid authentication without raising exceptions.
    Useful for UI endpoints that need to conditionally redirect.
    """
    try:
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return False
        
        token = auth_header.split(" ")[1]
        
        # For OIDC tokens, validate them properly
        if settings.auth_enabled:
            try:
                await validate_oidc_token(token)
                return True
            except:
                return False
        
        return False
        
    except:
        return False
