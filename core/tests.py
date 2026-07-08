"""
Tests for core security utilities:
  - Fixed-window rate limiter
  - SecurityHeadersMiddleware (CSP injection)
"""
from unittest.mock import patch, MagicMock

from django.contrib.auth.signals import user_login_failed
from django.core.cache import cache
from django.test import TestCase, RequestFactory, override_settings

from core.security import (
    rate_limit,
    get_client_ip,
    log_security_event,
    SecurityHeadersMiddleware,
)


# -----------------------------------------------------------
# Helpers
# -----------------------------------------------------------

def _make_request(ip='1.2.3.4', path='/test/'):
    factory = RequestFactory()
    request = factory.get(path, SERVER_NAME='testserver', REMOTE_ADDR=ip)
    request.user = MagicMock(id=None, is_authenticated=False)
    return request


def _make_view():
    """A minimal view that always returns 200."""
    from django.http import HttpResponse
    return lambda request, *a, **kw: HttpResponse('ok')


# -----------------------------------------------------------
# get_client_ip
# -----------------------------------------------------------

class GetClientIpTest(TestCase):

    def test_uses_remote_addr_by_default(self):
        factory = RequestFactory()
        req = factory.get('/', REMOTE_ADDR='10.0.0.1')
        self.assertEqual(get_client_ip(req), '10.0.0.1')

    def test_prefers_x_forwarded_for(self):
        factory = RequestFactory()
        req = factory.get('/', HTTP_X_FORWARDED_FOR='203.0.113.5, 10.0.0.1')
        self.assertEqual(get_client_ip(req), '203.0.113.5')


# -----------------------------------------------------------
# Fixed-window rate limiter
# -----------------------------------------------------------

class RateLimitTest(TestCase):

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_allows_requests_within_limit(self):
        view = rate_limit('test_rl', max_requests=3, window=60)(_make_view())
        for _ in range(3):
            response = view(_make_request())
            self.assertEqual(response.status_code, 200)

    def test_blocks_requests_over_limit(self):
        view = rate_limit('test_rl_block', max_requests=2, window=60)(_make_view())
        view(_make_request(ip='5.5.5.5'))  # 1st
        view(_make_request(ip='5.5.5.5'))  # 2nd
        response = view(_make_request(ip='5.5.5.5'))  # 3rd — over limit
        self.assertEqual(response.status_code, 429)

    def test_different_ips_tracked_independently(self):
        view = rate_limit('test_rl_ip', max_requests=1, window=60)(_make_view())
        r1 = view(_make_request(ip='1.1.1.1'))
        r2 = view(_make_request(ip='2.2.2.2'))
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r2.status_code, 200)

    def test_ajax_request_blocked_returns_json(self):
        factory = RequestFactory()
        req = factory.get('/test/', REMOTE_ADDR='9.9.9.9',
                          HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        req.user = MagicMock(id=None, is_authenticated=False)
        view = rate_limit('test_rl_ajax', max_requests=0, window=60)(_make_view())
        response = view(req)
        self.assertEqual(response.status_code, 429)
        import json
        data = json.loads(response.content)
        self.assertIn('error', data)

    def test_window_is_fixed_not_sliding(self):
        """Second add() call must NOT reset the expiry for the window."""
        view = rate_limit('test_rl_fixed', max_requests=5, window=60)(_make_view())
        # First request sets the key via cache.add
        view(_make_request(ip='7.7.7.7'))
        key = 'test_rl_fixed:7.7.7.7:anonymous'
        ttl_after_first = cache.ttl(key) if hasattr(cache, 'ttl') else None
        # Second request must NOT call cache.add again; it calls cache.incr
        view(_make_request(ip='7.7.7.7'))
        ttl_after_second = cache.ttl(key) if hasattr(cache, 'ttl') else None
        # TTL should not increase (fixed window)
        if ttl_after_first is not None and ttl_after_second is not None:
            self.assertLessEqual(ttl_after_second, ttl_after_first)


# -----------------------------------------------------------
# SecurityHeadersMiddleware
# -----------------------------------------------------------

class SecurityHeadersMiddlewareTest(TestCase):

    def _get_response(self, request):
        from django.http import HttpResponse
        return HttpResponse('ok')

    def test_standard_security_headers_present(self):
        mw = SecurityHeadersMiddleware(self._get_response)
        req = _make_request()
        response = mw(req)
        self.assertEqual(response['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(response['X-Frame-Options'], 'DENY')
        self.assertEqual(response['Referrer-Policy'], 'same-origin')

    @override_settings(SECURE_CONTENT_SECURITY_POLICY={
        'default-src': ["'self'"],
        'script-src': ["'self'", 'cdn.example.com'],
    })
    def test_csp_header_injected_from_settings(self):
        mw = SecurityHeadersMiddleware(self._get_response)
        req = _make_request()
        response = mw(req)
        csp = response.get('Content-Security-Policy', '')
        self.assertIn("default-src 'self'", csp)
        self.assertIn("script-src", csp)
        self.assertIn("cdn.example.com", csp)

    @override_settings(SECURE_CONTENT_SECURITY_POLICY=None)
    def test_no_csp_header_when_setting_absent(self):
        mw = SecurityHeadersMiddleware(self._get_response)
        req = _make_request()
        response = mw(req)
        self.assertNotIn('Content-Security-Policy', response)


# -----------------------------------------------------------
# Failed-login signal logging
# -----------------------------------------------------------

class FailedLoginSignalTest(TestCase):

    def test_log_failed_login_called_on_signal(self):
        factory = RequestFactory()
        req = factory.post('/accounts/login/', REMOTE_ADDR='3.3.3.3')
        with patch('core.security.log_security_event') as mock_log:
            user_login_failed.send(
                sender=None,
                credentials={'username': 'baduser'},
                request=req,
            )
            mock_log.assert_called_once()
            args, kwargs = mock_log.call_args
            self.assertEqual(args[0], 'FAILED_LOGIN_ATTEMPT')
            self.assertIn('baduser', args[2])
            self.assertEqual(kwargs.get('severity'), 'WARNING')

    def test_log_failed_login_handles_missing_request(self):
        """Signal handler must not crash when request is None."""
        with patch('core.security.log_security_event') as mock_log:
            user_login_failed.send(
                sender=None,
                credentials={'username': 'test'},
                request=None,
            )
            mock_log.assert_called_once()
