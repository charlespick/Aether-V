"""Authentication and authorization middleware."""
import logging
from typing import Optional
from fastapi import Depends, HTTPException, status, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from authlib.integrations.starlette_client import OAuth
from authlib.jose import jwt, JoseError
import httpx

from .config import settings

logger = logging.getLogger(__name__)

security = HTTPBearer(auto_error=False)

# OAuth client for OIDC
oauth = OAuth()

if settings.oidc_enabled and settings.oidc_issuer_url and settings.oidc_client_id:
    oauth.register(
        name='oidc',
        client_id=settings.oidc_client_id,
        client_secret=settings.oidc_client_secret,
        server_metadata_url=f"{settings.oidc_issuer_url}/.well-known/openid-configuration",
        client_kwargs={
            'scope': 'openid profile email',
            'token_endpoint_auth_method': 'client_secret_post',
        }
    )


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(security)
) -> dict:
    """
    Validate authentication and return user info.
    
    Supports:
    - OIDC bearer token (JWT)
    - Static API token (for development/automation)
    - No auth if OIDC is disabled (development mode)
    """
    # If OIDC is disabled, allow all requests (development mode)
    if not settings.oidc_enabled:
        logger.warning("OIDC authentication is disabled - allowing all requests")
        return {"sub": "dev-user", "roles": [settings.oidc_role_name]}
    
    # Check for credentials
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    token = credentials.credentials
    
    # Check static API token first (for automation)
    if settings.api_token and token == settings.api_token:
        logger.info("Request authenticated with static API token")
        return {"sub": "api-user", "roles": [settings.oidc_role_name]}
    
    # Validate OIDC token
    try:
        user_info = await validate_oidc_token(token)
        
        # Check for required role
        user_roles = user_info.get("roles", [])
        if settings.oidc_role_name not in user_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"User does not have required role: {settings.oidc_role_name}",
            )
        
        return user_info
    
    except JoseError as e:
        logger.error(f"Token validation failed: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )


async def validate_oidc_token(token: str) -> dict:
    """
    Validate an OIDC JWT token.
    
    This is a simplified implementation. In production, you should:
    - Cache JWKS keys
    - Validate issuer, audience, expiration
    - Handle key rotation
    """
    if not settings.oidc_issuer_url:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OIDC is not configured"
        )
    
    try:
        # Fetch JWKS keys from the OIDC provider
        async with httpx.AsyncClient() as client:
            jwks_uri = f"{settings.oidc_issuer_url}/.well-known/openid-configuration"
            config_response = await client.get(jwks_uri)
            config_response.raise_for_status()
            config = config_response.json()
            
            jwks_response = await client.get(config["jwks_uri"])
            jwks_response.raise_for_status()
            jwks = jwks_response.json()
        
        # Decode and validate the token
        claims = jwt.decode(token, jwks)
        claims.validate()
        
        return dict(claims)
    
    except Exception as e:
        logger.error(f"OIDC token validation error: {e}")
        raise JoseError(f"Token validation failed: {e}")


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
