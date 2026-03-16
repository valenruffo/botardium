"""
Botardium Core — Retry Utilities
=================================
Sistema de retry con exponential backoff y manejo de errores específicos.

FASE 5: Error Handling & Retry Logic
- Exponential backoff con jitter
- Categorización de errores (rate_limit, action_blocked, network, etc.)
- Captura de screenshots en errores para debugging
- Retry solo de errores recuperables
"""

import asyncio
import logging
import random
import time
from enum import Enum
from typing import Callable, Optional, TypeVar, Any
from functools import wraps
from pathlib import Path

from scripts.runtime_paths import TMP_DIR

logger = logging.getLogger("botardium.retry")

T = TypeVar('T')


class RetryableError(str, Enum):
    """Errores recuperables que deben dispara retry."""
    RATE_LIMIT = "rate_limit"
    ACTION_BLOCKED = "action_blocked"
    NETWORK_ERROR = "network_error"
    TIMEOUT = "timeout"
    SERVER_ERROR = "server_error"
    SESSION_EXPIRED = "session_expired"
    UNKNOWN = "unknown"


class NonRetryableError(str, Enum):
    """Errores no recuperables - no deben reintentarse."""
    AUTH_FAILED = "auth_failed"
    INVALID_CREDENTIALS = "invalid_credentials"
    ACCOUNT_BANNED = "account_banned"
    PERMISSION_DENIED = "permission_denied"


RETRYABLE_PATTERNS = {
    RetryableError.RATE_LIMIT: [
        "rate limit",
        "too many requests",
        "try again later",
        "限流",
        "rate_limit",
    ],
    RetryableError.ACTION_BLOCKED: [
        "action blocked",
        "you can't message",
        "cannot send message",
        "bloqueado de acciones",
    ],
    RetryableError.NETWORK_ERROR: [
        "network error",
        "connection error",
        "connection reset",
        "timeout",
        "econnrefused",
        "enotfound",
    ],
    RetryableError.SESSION_EXPIRED: [
        "session expired",
        "login required",
        "not logged in",
        "csrf",
    ],
    RetryableError.SERVER_ERROR: [
        "500 internal server error",
        "502 bad gateway",
        "503 service unavailable",
        "504 gateway timeout",
    ],
}


def categorize_error(error: Exception | str) -> RetryableError | NonRetryableError:
    """Categoriza un error como recuperable o no."""
    error_str = str(error).lower()
    
    for retryable_type, patterns in RETRYABLE_PATTERNS.items():
        for pattern in patterns:
            if pattern.lower() in error_str:
                return retryable_type
    
    return RetryableError.UNKNOWN


def is_retryable(error: Exception | str) -> bool:
    """Determina si un error debe disparar retry."""
    category = categorize_error(error)
    return category in (
        RetryableError.RATE_LIMIT,
        RetryableError.ACTION_BLOCKED,
        RetryableError.NETWORK_ERROR,
        RetryableError.TIMEOUT,
        RetryableError.SERVER_ERROR,
        RetryableError.SESSION_EXPIRED,
        RetryableError.UNKNOWN,
    )


async def retry_with_backoff(
    func: Callable[..., T],
    *args,
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: float = 0.5,
    retryable_only: bool = True,
    on_retry: Optional[Callable[[Exception, int], None]] = None,
    **kwargs,
) -> T:
    """
    Ejecuta una función con retry automático y exponential backoff.
    
    Args:
        func: Función a ejecutar
        max_retries: Máximo número de reintentos
        base_delay: Delay inicial en segundos
        max_delay: Delay máximo en segundos
        exponential_base: Base para el crecimiento exponencial
        jitter: Factor de aleatoriedad (0.0 = sin jitter, 0.5 = ±50%)
        retryable_only: Si True, solo reintenta errores recuperables
        on_retry: Callback opcional llamado antes de cada retry
    
    Returns:
        El resultado de func()
    
    Raises:
        El último error si todos los retries fallan
    """
    last_exception = None
    
    for attempt in range(max_retries + 1):
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        except Exception as e:
            last_exception = e
            
            if attempt == max_retries:
                logger.error(f"All {max_retries} retries exhausted. Last error: {e}")
                raise
            
            if retryable_only and not is_retryable(e):
                logger.warning(f"Non-retryable error, failing fast: {e}")
                raise
            
            delay = min(base_delay * (exponential_base ** attempt), max_delay)
            jitter_range = delay * jitter
            actual_delay = delay + random.uniform(-jitter_range, jitter_range)
            
            category = categorize_error(e)
            logger.warning(
                f"Retryable error (attempt {attempt + 1}/{max_retries + 1}, "
                f"delay {actual_delay:.1f}s): {category.value} - {e}"
            )
            
            if on_retry:
                on_retry(e, attempt + 1)
            
            await asyncio.sleep(actual_delay)
    
    raise last_exception


def with_retry(
    max_retries: int = 3,
    base_delay: float = 2.0,
    max_delay: float = 60.0,
    exponential_base: float = 2.0,
    jitter: float = 0.5,
    retryable_only: bool = True,
):
    """
    Decorador para añadir retry con exponential backoff a funciones async.
    
    Usage:
        @with_retry(max_retries=3, base_delay=5.0)
        async def my_function():
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            return await retry_with_backoff(
                func,
                *args,
                max_retries=max_retries,
                base_delay=base_delay,
                max_delay=max_delay,
                exponential_base=exponential_base,
                jitter=jitter,
                retryable_only=retryable_only,
                **kwargs,
            )
        return wrapper
    return decorator


async def capture_error_screenshot(
    page,
    context: str,
    prefix: str = "error",
) -> Optional[Path]:
    """
    Captura un screenshot cuando ocurre un error para debugging.
    
    Args:
        page: Playwright page object
        context: Contexto/donde ocurrió el error
        prefix: Prefijo para el nombre del archivo
    
    Returns:
        Path al screenshot o None si falla
    """
    try:
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        filename = f"{prefix}_{context}_{timestamp}.png"
        filepath = TMP_DIR / filename
        
        await page.screenshot(path=str(filepath), full_page=True)
        logger.info(f"Screenshot guardado: {filepath}")
        return filepath
    except Exception as e:
        logger.warning(f"Failed to capture screenshot: {e}")
        return None


async def safe_operation(
    page,
    operation_name: str,
    operation: Callable,
    max_retries: int = 3,
    capture_screenshot_on_error: bool = True,
) -> Any:
    """
    Ejecuta una operación con retry y captura de screenshots automáticamente.
    
    Args:
        page: Playwright page
        operation_name: Nombre descriptivo para logs
        operation: Función async a ejecutar
        max_retries: Número máximo de reintentos
        capture_screenshot_on_error: Si True, captura screenshot en cada error
    
    Returns:
        Resultado de la operación
    
    Raises:
        Exception si todos los retries fallan
    """
    last_error = None
    
    for attempt in range(max_retries + 1):
        try:
            return await operation()
        except Exception as e:
            last_error = e
            
            if capture_screenshot_on_error and page:
                await capture_error_screenshot(
                    page,
                    f"{operation_name}_attempt_{attempt + 1}",
                    prefix="error"
                )
            
            if attempt == max_retries:
                break
            
            if not is_retryable(e):
                logger.warning(f"Non-retryable error in {operation_name}: {e}")
                break
            
            delay = min(5 * (2 ** attempt), 60)
            logger.warning(
                f"Operation '{operation_name}' failed (attempt {attempt + 1}/{max_retries + 1}), "
                f"retrying in {delay}s: {e}"
            )
            await asyncio.sleep(delay)
    
    raise last_error
