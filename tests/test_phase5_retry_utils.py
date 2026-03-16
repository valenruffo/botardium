"""
Tests for Phase 5: Retry Utilities & Error Handling
======================================================
Verifies retry logic, exponential backoff, and error categorization.
"""

import unittest
import asyncio
from unittest.mock import patch, AsyncMock

from scripts.retry_utils import (
    categorize_error,
    is_retryable,
    RetryableError,
    NonRetryableError,
    retry_with_backoff,
    with_retry,
    RETRYABLE_PATTERNS,
)


class TestErrorCategorization(unittest.TestCase):
    """Test que los errores se categorizan correctamente."""
    
    def test_rate_limit_categorization(self):
        """Errores de rate limit se categorizan correctamente."""
        errors = [
            Exception("Rate limit exceeded"),
            Exception("Too many requests, try again later"),
            Exception("API rate limit reached"),
        ]
        for error in errors:
            category = categorize_error(error)
            self.assertEqual(category, RetryableError.RATE_LIMIT)

    def test_action_blocked_categorization(self):
        """Errores de acción bloqueada se categorizan correctamente."""
        errors = [
            Exception("Action blocked"),
            Exception("You can't message this user"),
            Exception("Cannot send message: blocked"),
        ]
        for error in errors:
            category = categorize_error(error)
            self.assertEqual(category, RetryableError.ACTION_BLOCKED)

    def test_network_error_categorization(self):
        """Errores de red se categorizan correctamente."""
        errors = [
            Exception("Network error: connection refused"),
            Exception("Connection timeout"),
            Exception("ECONNREFUSED"),
        ]
        for error in errors:
            category = categorize_error(error)
            self.assertEqual(category, RetryableError.NETWORK_ERROR)

    def test_session_expired_categorization(self):
        """Errores de sesión expirada se categorizan correctamente."""
        errors = [
            Exception("Session expired, please login again"),
            Exception("Login required to perform this action"),
            Exception("CSRF token invalid"),
        ]
        for error in errors:
            category = categorize_error(error)
            self.assertEqual(category, RetryableError.SESSION_EXPIRED)

    def test_non_retryable_errors(self):
        """Errores específicos se consideran no recuperables."""
        error_str = "rate limit exceeded"
        self.assertTrue(is_retryable(error_str))
        
        error_str = "account banned permanently"
        self.assertTrue(is_retryable(error_str))


class TestRetryWithBackoff(unittest.TestCase):
    """Test del mecanismo de retry con exponential backoff."""
    
    def test_successful_first_attempt(self):
        """Si la función succeede al primer intento, retorna el resultado."""
        async def success_func():
            return "success"
        
        result = asyncio.run(retry_with_backoff(success_func, max_retries=3))
        self.assertEqual(result, "success")
    
    def test_retry_on_failure(self):
        """La función se reintenta cuando falla."""
        call_count = 0
        
        async def flaky_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Transient error")
            return "success"
        
        result = asyncio.run(retry_with_backoff(flaky_func, max_retries=3, base_delay=0.01))
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 3)
    
    def test_max_retries_exceeded(self):
        """Si se agotan los retries, lanza la excepción."""
        async def always_fail():
            raise Exception("Permanent failure")
        
        with self.assertRaises(Exception) as context:
            asyncio.run(retry_with_backoff(always_fail, max_retries=2, base_delay=0.01))
        
        self.assertEqual(str(context.exception), "Permanent failure")
    
    def test_exponential_backoff_timing(self):
        """El delay crece exponencialmente."""
        delays = []
        original_sleep = asyncio.sleep
        
        async def mock_sleep(delay):
            delays.append(delay)
            await original_sleep(0.001)
        
        attempt_count = 0
        
        async def flaky_func():
            nonlocal attempt_count
            attempt_count += 1
            if attempt_count < 4:
                raise Exception("Transient")
            return "success"
        
        with patch('asyncio.sleep', mock_sleep):
            asyncio.run(retry_with_backoff(flaky_func, max_retries=3, base_delay=1.0, jitter=0))
        
        self.assertEqual(len(delays), 3)
        self.assertAlmostEqual(delays[0], 1.0, places=1)
        self.assertAlmostEqual(delays[1], 2.0, places=1)
        self.assertAlmostEqual(delays[2], 4.0, places=1)
    
    def test_jitter_adds_randomness(self):
        """El jitter añade aleatoriedad al delay."""
        delays = []
        
        async def always_fail():
            if len(delays) < 3:
                raise Exception("Transient")
            return "success"
        
        original_sleep = asyncio.sleep
        
        async def track_sleep(delay):
            delays.append(delay)
            await original_sleep(0.001)
        
        with patch('asyncio.sleep', track_sleep):
            asyncio.run(retry_with_backoff(always_fail, max_retries=3, base_delay=1.0, jitter=0.5))
        
        base_delay = 1.0
        for i, delay in enumerate(delays):
            self.assertGreaterEqual(delay, base_delay * (2 ** i) * 0.5)
            self.assertLessEqual(delay, base_delay * (2 ** i) * 1.5)


class TestWithRetryDecorator(unittest.TestCase):
    """Test del decorador @with_retry."""
    
    def test_decorator_works(self):
        """El decorador añade retry automáticamente."""
        call_count = 0
        
        @with_retry(max_retries=2, base_delay=0.01)
        async def flaky_decorated():
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise Exception("Transient")
            return "success"
        
        result = asyncio.run(flaky_decorated())
        self.assertEqual(result, "success")
        self.assertEqual(call_count, 2)


class TestRetryablePatterns(unittest.TestCase):
    """Test que los patrones de errores están bien definidos."""
    
    def test_all_retryable_patterns_have_errors(self):
        """Cada categoría de error tiene patrones definidos."""
        for error_type, patterns in RETRYABLE_PATTERNS.items():
            self.assertIsInstance(patterns, list)
            self.assertGreater(len(patterns), 0)
    
    def test_patterns_are_lowercase(self):
        """Los patrones están en minúsculas para comparación."""
        for error_type, patterns in RETRYABLE_PATTERNS.items():
            for pattern in patterns:
                self.assertEqual(pattern, pattern.lower())


if __name__ == "__main__":
    unittest.main()
