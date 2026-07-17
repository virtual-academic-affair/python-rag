import jwt
import logging
from typing import Optional

from fastapi import HTTPException, status
from pydantic import BaseModel, Field, ValidationError

from app.core.config import settings

logger = logging.getLogger(__name__)

class JWTPayload(BaseModel):
    sub: str
    email: str = ""
    role: str = "student"
    student_code: Optional[str] = Field(default=None, alias="studentCode")
    enrollment_year: Optional[int] = Field(default=None, alias="enrollmentYear")

    model_config = {"populate_by_name": True, "coerce_numbers_to_str": True}

    @property
    def user_id(self) -> str:
        return self.sub

    @property
    def display_name(self) -> str:
        return self.email.split("@")[0] if self.email else "Unknown"


def verify_token_local(token: str) -> JWTPayload:
    """Verify JWT token locally using PyJWT library.
    
    Raises:
        HTTPException (401) if invalid or expired.
        HTTPException (500) if any server side processing error occurs.
    """
    try:
        payload = jwt.decode(
            token,
            settings.JWT_SECRET,
            algorithms=["HS256"],
            audience=settings.JWT_TOKEN_AUDIENCE,
            issuer=settings.JWT_TOKEN_ISSUER,
            options={"verify_sub": False},
        )
        
        # Verify subject claim exists
        if "sub" not in payload:
            logger.warning("Local verification failed: token is missing 'sub' claim")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token payload is missing subject claim",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        # Normalize fields for downstream workflows using Pydantic
        # NestJS sends sub as int — coerce to str explicitly to ensure model_validate succeeds
        payload["sub"] = str(payload["sub"])
        try:
            jwt_payload = JWTPayload.model_validate(payload)
        except ValidationError as val_err:
            logger.warning("Local token payload validation failed: %s", val_err)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token payload structure",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        logger.debug("Local token verified successfully for user: %s", jwt_payload.email)
        return jwt_payload
        
    except jwt.ExpiredSignatureError as exc:
        logger.warning("Local token verification failed: token has expired: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except jwt.InvalidTokenError as exc:
        logger.warning("Local token verification failed: invalid token signature or claims: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token is invalid",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        logger.error("Unexpected error during local token verification: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error during token verification",
        ) from exc
