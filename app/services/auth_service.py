"""Authentication service for JWT verification and Redis token validation"""
import logging
import json
import jwt
import redis
from typing import Optional, Dict, Any
from fastapi import HTTPException, status
from config.settings import settings

logger = logging.getLogger(__name__)


class AuthService:
    """Service for handling JWT authentication and Redis token validation"""
    
    def __init__(self):
        """Initialize Redis connection (lazy connection)"""
        self.redis_client = None
        self._redis_connected = False
    
    def _ensure_redis_connection(self):
        """Ensure Redis connection is established"""
        if self._redis_connected and self.redis_client:
            try:
                self.redis_client.ping()
                return
            except:
                self._redis_connected = False
                self.redis_client = None
        
        try:
            redis_kwargs = {
                "host": settings.REDIS_HOST,
                "port": settings.REDIS_PORT,
                "db": settings.REDIS_DB,
                "decode_responses": True,
                "socket_connect_timeout": 5,
                "socket_timeout": 5
            }
            
            if settings.REDIS_PASSWORD:
                redis_kwargs["password"] = settings.REDIS_PASSWORD
            
            self.redis_client = redis.Redis(**redis_kwargs)
            # Test connection
            self.redis_client.ping()
            self._redis_connected = True
            logger.info(f"Redis connection established: {settings.REDIS_HOST}:{settings.REDIS_PORT}")
        except Exception as e:
            logger.error(f"Failed to connect to Redis: {str(e)}")
            self._redis_connected = False
            raise
    
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
    
    def get_token_from_redis(self, token_key: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve token data from Redis.
        
        Args:
            token_key: Key to look up in Redis (typically the JWT token or a derived key)
            
        Returns:
            Token data from Redis if found, None otherwise
        """
        try:
            self._ensure_redis_connection()
            data = self.redis_client.get(token_key)
            if data:
                return json.loads(data)
            return None
        except redis.RedisError as e:
            logger.error(f"Redis error: {str(e)}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"Error decoding Redis data: {str(e)}")
            return None
        except Exception as e:
            logger.error(f"Error connecting to Redis: {str(e)}")
            return None
    
    def verify_token(self, token: str) -> Dict[str, Any]:
        """
        Verify token by decoding JWT and checking in Redis.
        
        Args:
            token: Bearer token string
            
        Returns:
            User data from Redis if token is valid
            
        Raises:
            HTTPException: If token is invalid or not found in Redis
        """
        # Decode JWT to get token identifier
        jwt_payload = self.decode_jwt(token)
        
        # Try multiple key formats to find token in Redis
        # 1. Full token as key (most common)
        # 2. JWT ID (jti) if present
        # 3. Subject (sub) if present
        possible_keys = [token]
        
        if 'jti' in jwt_payload:
            possible_keys.append(jwt_payload['jti'])
        if 'sub' in jwt_payload:
            possible_keys.append(jwt_payload['sub'])
        
        # Try each key format
        redis_data = None
        used_key = None
        for key in possible_keys:
            redis_data = self.get_token_from_redis(key)
            if redis_data:
                used_key = key
                break
        
        if not redis_data:
            logger.warning(f"Token not found in Redis (tried keys: {[k[:20] + '...' if len(k) > 20 else k for k in possible_keys]})")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token not found or has been revoked"
            )
        
        # Merge JWT payload with Redis data (Redis data takes precedence)
        result = {**jwt_payload, **redis_data}
        
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

