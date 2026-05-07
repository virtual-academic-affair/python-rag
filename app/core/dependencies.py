import logging
from typing import Dict, Any
from fastapi import Depends, Header, HTTPException, status, Request
from app.integrations.grpc.client import get_grpc_client
from pydantic import ValidationError

logger = logging.getLogger(__name__)


def from_form(model_cls):
    """Helper to inject Form data into a Pydantic model.
    Used for endpoints accepting multipart/form-data where 
    the parameters should be mapped to a model."""
    async def dependency(request: Request):
        form_data = await request.form()
        try:
            return model_cls.model_validate(dict(form_data))
        except ValidationError as e:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=e.errors()
            )
    return dependency




async def _extract_token(authorization: str = Header(None, alias="Authorization")) -> str:
    if not authorization:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header must start with 'Bearer '",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = authorization[7:].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is empty",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return token


async def require_auth(token: str = Depends(_extract_token)) -> Dict[str, Any]:
    client = get_grpc_client()

    # If gRPC is disabled, reject all protected requests
    if not client._config.enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service is disabled",
        )

    try:
        payload = await client.verify_token(token)
    except Exception as e:
        logger.error(f"Unexpected error during token verification: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication service error",
        )

    if payload is None:
        # Distinguish between unavailable server and invalid token via client logs.
        # verify_token() logs detailed reason internally, return generic 401 to client.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid or expired",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


async def require_admin(user: Dict[str, Any] = Depends(require_auth)) -> Dict[str, Any]:
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin role required",
        )
    return user
