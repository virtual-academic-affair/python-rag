"""Authentication service for JWT verification and RabbitMQ token validation"""
import logging
import json
import jwt
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from config.settings import settings
from app.services.rabbitmq_service import get_rabbitmq_service

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling JWT authentication and RabbitMQ token validation"""

    def __init__(self):
        """Initialize RabbitMQ service"""
        self.rabbitmq_service = get_rabbitmq_service()

    def decode_jwt(self, token: str) -> Dict[str, Any]:
        """
        Decode and verify JWT token.
        
        Args:
            token: JWT token string
            
        Returns:
            Decoded token payload
            
        Raises:
            HTTPException: If token is invalid or expired
        """
        try:
            payload = jwt.decode(
                token,
                settings.JWT_SECRET_KEY,
                algorithms=[settings.JWT_ALGORITHM]
            )
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("JWT token has expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired"
            )
        except jwt.InvalidTokenError as e:
            logger.warning(f"Invalid JWT token: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"Invalid token: {str(e)}"
            )
        except Exception as e:
            logger.error(f"Error decoding JWT: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Error processing token"
            )
    
    def get_token_from_rabbitmq(self, token_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve token data from RabbitMQ.

        Args:
            token_key: Key to look up in RabbitMQ (typically the JWT token or a derived key)

        Returns:
            Token data from RabbitMQ if found, None otherwise
        """
        try:
            data = self.rabbitmq_service.get_token(token_key)
            if data:
                return data
            return None
        except Exception as e:
            logger.error(f"Error retrieving token from RabbitMQ: {str(e)}")
            return None
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify token by decoding JWT and checking in RabbitMQ.

        Args:
            token: Bearer token string

        Returns:
            User data from RabbitMQ if token is valid

        Raises:
            HTTPException: If token is invalid or not found in RabbitMQ
        """
        # Decode JWT to get token identifier
        jwt_payload = self.decode_jwt(token)

        # Try multiple key formats to find token in RabbitMQ
        # 1. Full token as key (most common)
        # 2. JWT ID (jti) if present
        # 3. Subject (sub) if present
        possible_keys = [token]

        if 'jti' in jwt_payload:
            possible_keys.append(jwt_payload['jti'])
        if 'sub' in jwt_payload:
            possible_keys.append(jwt_payload['sub'])

        # Try each key format
        rabbitmq_data = None
        used_key = None
        for key in possible_keys:
            rabbitmq_data = self.get_token_from_rabbitmq(key)
            if rabbitmq_data:
                used_key = key
                break

        if not rabbitmq_data:
            logger.warning(f"Token not found in RabbitMQ (tried keys: {[k[:20] + '...' if len(k) > 20 else k for k in possible_keys]})")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token not found or has been revoked"
            )

        # Merge JWT payload with RabbitMQ data (RabbitMQ data takes precedence)
        result = {**jwt_payload, **rabbitmq_data}

        logger.info(f"Token verified successfully for user: {result.get('email', result.get('sub', 'unknown'))} (key: {used_key[:20] if used_key and len(used_key) > 20 else used_key}...)")
        return result


# Global auth service instance
_auth_service: Optional[AuthService] = None


def get_auth_service() -> AuthService:
    """Get or create auth service instance"""
    global _auth_service
    if _auth_service is None:
        _auth_service = AuthService()
    return _auth_service

