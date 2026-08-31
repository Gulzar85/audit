"""
Security utilities for rate limiting, logging, and access control.
"""
import logging
import secrets
from functools import wraps
from django.core.cache import cache
from django.http import JsonResponse


logger = logging.getLogger('django.security')


def log_security_event(event_type, user, details, severity='INFO'):
    """Log security-related events for audit trail."""
    message = (
        f"[{event_type}] User: {user.username if user else 'Anonymous'} | "
        f"Details: {details}"
    )
    if severity == 'CRITICAL':
        logger.critical(message)
    elif severity == 'WARNING':
        logger.warning(message)
    else:
        logger.info(message)


def rate_limit(key_prefix, max_requests=5, window=300):
    """
    Rate limiting decorator using Django cache (Fixed Window).
    
    Args:
        key_prefix: Cache key prefix (e.g., 'login_attempts')
        max_requests: Maximum requests allowed in window
        window: Time window in seconds (default 5 minutes)
    """
    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            # Create cache key from IP + user + prefix
            ip = get_client_ip(request)
            user_identifier = request.user.id if request.user.is_authenticated else 'anonymous'
            cache_key = f"{key_prefix}:{ip}:{user_identifier}"
            
            # Atomically increment counter with a fixed window
            try:
                if cache.add(cache_key, 1, window):
                    attempts = 1
                else:
                    try:
                        attempts = cache.incr(cache_key)
                    except ValueError:
                        cache.set(cache_key, 1, window)
                        attempts = 1
            except Exception:
                import logging
                logger = logging.getLogger(__name__)
                logger.error('Rate limit cache failure — denying request for safety')
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {'error': 'Service temporarily unavailable. Please try again later.'},
                        status=503
                    )
                else:
                    from django.http import HttpResponse
                    return HttpResponse(
                        'Service temporarily unavailable.',
                        status=503
                    )
            
            if attempts > max_requests:
                log_security_event(
                    'RATE_LIMIT_EXCEEDED',
                    request.user,
                    f"IP: {ip}, Endpoint: {request.path}",
                    severity='WARNING'
                )
                
                if request.headers.get('x-requested-with') == 'XMLHttpRequest':
                    return JsonResponse(
                        {'error': 'Too many requests. Please try again later.'},
                        status=429
                    )
                else:
                    from django.http import HttpResponse
                    return HttpResponse(
                        'Too many requests. Please try again later.',
                        status=429
                    )
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def get_client_ip(request):
    """Extract client IP from request, handling proxies safely.

    X-Forwarded-For is fully attacker-controlled unless the request actually
    passed through a known number of trusted reverse proxies (TRUSTED_PROXY_COUNT).
    Without that configuration, trusting it lets a client bypass IP-based rate
    limiting simply by sending a different header value on every request, so we
    fall back to REMOTE_ADDR (which the client cannot spoof) by default.
    """
    from django.conf import settings
    trusted_proxies = getattr(settings, 'TRUSTED_PROXY_COUNT', 0)
    if trusted_proxies > 0:
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            parts = [p.strip() for p in x_forwarded_for.split(',') if p.strip()]
            if parts:
                # The last `trusted_proxies` entries were appended by our own
                # trusted proxies; the entry just before them is the real client.
                index = max(0, len(parts) - trusted_proxies)
                return parts[index]
    return request.META.get('REMOTE_ADDR')


def check_suspicious_activity(request, action_type, threshold=10):
    """
    Detect suspicious activity patterns using atomic cache increment.
    
    Args:
        request: Django request object
        action_type: Type of action (e.g., 'failed_login', 'bulk_export')
        threshold: Number of actions to trigger alert
    
    Returns:
        bool: True if suspicious activity detected
    """
    ip = get_client_ip(request)
    cache_key = f"suspicious:{action_type}:{ip}"
    
    # Atomic fixed-window counter (same pattern as rate_limit)
    try:
        if cache.add(cache_key, 1, 3600):
            attempts = 1
        else:
            try:
                attempts = cache.incr(cache_key)
            except ValueError:
                cache.set(cache_key, 1, 3600)
                attempts = 1
    except Exception:
        import logging
        logger = logging.getLogger(__name__)
        logger.error('Suspicious activity check cache failure — treating as suspicious for safety')
        return True
    
    if attempts >= threshold:
        log_security_event(
            'SUSPICIOUS_ACTIVITY',
            request.user,
            f"Action: {action_type}, IP: {ip}, Attempts: {attempts}",
            severity='CRITICAL'
        )
        return True
    
    return False


# Middleware classes


class SecurityHeadersMiddleware:
    """Middleware to add additional security headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)

        # Prevent caching of authenticated pages
        if request.user.is_authenticated:
            response['Cache-Control'] = 'no-store, no-cache, must-revalidate, private'
            response['Pragma'] = 'no-cache'
            response['Expires'] = '0'

        # Content Security Policy (from settings)
        from django.conf import settings
        csp = getattr(settings, 'SECURE_CONTENT_SECURITY_POLICY', None)
        if csp and isinstance(csp, dict):
            parts = []
            for directive, sources in csp.items():
                parts.append(f"{directive} {' '.join(sources)}")
            response['Content-Security-Policy'] = '; '.join(parts)

        return response
