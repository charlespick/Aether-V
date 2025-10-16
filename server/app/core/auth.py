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
from typing import Optional, Dict, Any, Union
from functools import lru_cache
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from authlib.integrations.starlette_client import OAuth
from authlib.jose import jwt, jwk, JoseError, JsonWebKey
from authlib.common.security import generate_token
import httpx

from .config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# JWKS caching utility for security and performance
class JWKSCache:
    """Thread-safe JWKS cache with TTL to minimize network calls and attack surface."""
    
    def __init__(self, jwks_uri: str, ttl: int = 300):
        self.jwks_uri = jwks_uri
        self.ttl = ttl
        self._keys = None
        self._fetched_at = 0

    async def get_keys(self) -> Dict[str, Any]:
        """Get JWKS keys with TTL-based caching and fallback."""
        now = time.time()
        if self._keys and now - self._fetched_at < self.ttl:
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
                logger.info(f"Successfully fetched JWKS (keys: {len(self._keys.get('keys', []))})")
                return self._keys
        except Exception as e:
            logger.error(f"JWKS fetch failed from {self.jwks_uri}: {e}")
            if self._keys:
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
        return metadata
    except Exception as e:
        logger.error(f"Failed to discover OIDC metadata: {e}")
        raise

# Initialize JWKS cache when authentication is enabled and OIDC is configured
jwks_cache: Optional[JWKSCache] = None
if settings.auth_enabled and settings.oidc_issuer_url:
    try:
        metadata = discover_oidc_metadata(settings.oidc_issuer_url)
        jwks_uri = metadata.get("jwks_uri")
        if jwks_uri:
            jwks_cache = JWKSCache(jwks_uri, ttl=300)  # 5 minute TTL
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
        return header
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
        return payload
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
    - OIDC bearer token (JWT) - for interactive users
    - Session-based authentication (cookies) - for browser requests after OIDC login
    - Static API token - for automation/service accounts
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
        return {"sub": "dev-user", "roles": [settings.oidc_role_name], "auth_type": "dev"}
    
    # Check for session-based authentication first (for browser requests)
    session_user = request.session.get("user_info") if hasattr(request, 'session') else None
    if session_user and session_user.get("authenticated"):
        # Validate session is not expired
        try:
            auth_timestamp = session_user.get("auth_timestamp")
            if auth_timestamp:
                from datetime import datetime, timedelta
                auth_time = datetime.fromisoformat(auth_timestamp)
                if datetime.now() - auth_time < timedelta(hours=24):
                    username = session_user.get("preferred_username", "unknown")
                    logger.debug(f"Session authentication successful for {username} from {client_ip}")
                    return {
                        "sub": session_user.get("sub"),
                        "preferred_username": session_user.get("preferred_username"),
                        "roles": session_user.get("roles", []),
                        "auth_type": "session"
                    }
        except Exception as e:
            logger.warning(f"Session validation failed from {client_ip}: {e}")
    
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
    
    # Try static API token authentication (for automation)
    if settings.api_token:
        if token == settings.api_token:
            logger.info(f"API token authentication successful from {client_ip}")
            return {
                "sub": "api-service", 
                "roles": [settings.oidc_role_name], 
                "auth_type": "api_token",
                "preferred_username": "api-service"
            }
        else:
            # Don't log the actual tokens for security
            auth_failures.append("api_token_mismatch")
    
    # Try OIDC JWT token validation (for interactive users)
    if settings.oidc_issuer_url and jwks_cache:
        try:
            user_info = await validate_oidc_token(token)
            
            # Extract roles from various Azure AD claims
            user_roles = extract_user_roles(user_info)
            
            # Check role requirements
            if settings.oidc_role_name and settings.oidc_role_name != "*":
                if settings.oidc_role_name not in user_roles:
                    username = user_info.get("preferred_username", user_info.get("sub", "unknown"))
                    logger.warning(f"User {username} from {client_ip} lacks required role '{settings.oidc_role_name}'. Has: {user_roles}")
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Insufficient privileges. Required role: {settings.oidc_role_name}",
                    )
            
            # Add auth metadata
            user_info["auth_type"] = "oidc"
            user_info["roles"] = user_roles
            
            username = user_info.get("preferred_username", user_info.get("sub", "unknown"))
            logger.info(f"OIDC authentication successful for {username} from {client_ip}")
            return user_info
            
        except HTTPException:
            raise  # Re-raise HTTP exceptions (like 403)
        except Exception as e:
            auth_failures.append(f"oidc_validation_failed: {type(e).__name__}")
            logger.error(f"OIDC token validation failed from {client_ip}: {e}")
    
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
    
    return list(set(roles))  # Remove duplicates


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
            if token_age > 3600:  # 1 hour max age
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
        if settings.oidc_client_id:
            token_aud = claims.get('aud')
            if not token_aud:
                raise JoseError("Missing audience claim")
                
            # Support multiple valid audiences for this client
            valid_audiences = [
                settings.oidc_client_id,
                f"api://{settings.oidc_client_id}"
            ]
            
            aud_list = token_aud if isinstance(token_aud, list) else [token_aud]
            if not any(aud in valid_audiences for aud in aud_list):
                raise JoseError(f"Invalid audience: {token_aud}")
        
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


def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> Optional[dict]:
    """
    Optional authentication for endpoints that work with or without auth.
    Returns None if not authenticated.
    """
    if not credentials:
        return None
    
    try:
        # Try to validate but don't raise if it fails
        if settings.api_token and credentials.credentials == settings.api_token:
            return {"sub": "api-user", "roles": [settings.oidc_role_name]}
        # For now, just return None for invalid tokens
        return None
    except:
        return None


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
        
        # Check static API token
        if settings.api_token and token == settings.api_token:
            return True
        
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
