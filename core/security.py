"""
Security utilities for rate limiting, logging, and access control.
"""
import logging
from functools import wraps
from django.core.cache import cache
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache

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
    Rate limiting decorator using Django cache.
    
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
            
            # Get current attempt count
            attempts = cache.get(cache_key, 0)
            
            if attempts >= max_requests:
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
            
            # Increment counter
            cache.set(cache_key, attempts + 1, window)
            
            return view_func(request, *args, **kwargs)
        
        return wrapper
    return decorator


def get_client_ip(request):
    """Extract client IP from request, handling proxies."""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0].strip()
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip


def check_suspicious_activity(request, action_type, threshold=10):
    """
    Detect suspicious activity patterns.
    
    Args:
        request: Django request object
        action_type: Type of action (e.g., 'failed_login', 'bulk_export')
        threshold: Number of actions to trigger alert
    
    Returns:
        bool: True if suspicious activity detected
    """
    ip = get_client_ip(request)
    cache_key = f"suspicious:{action_type}:{ip}"
    
    attempts = cache.get(cache_key, 0)
    
    if attempts >= threshold:
        log_security_event(
            'SUSPICIOUS_ACTIVITY',
            request.user,
            f"Action: {action_type}, IP: {ip}, Attempts: {attempts}",
            severity='CRITICAL'
        )
        return True
    
    # Increment and set 1-hour window
    cache.set(cache_key, attempts + 1, 3600)
    return False


def secure_redirect(request, next_url, allowed_hosts=None):
    """
    Safely redirect to next URL, preventing open redirect attacks.
    
    Args:
        request: Django request object
        next_url: URL to redirect to
        allowed_hosts: List of allowed hosts (defaults to ALLOWED_HOSTS)
    
    Returns:
        Validated URL or default redirect
    """
    from django.urls import reverse
    from urllib.parse import urlparse
    from django.conf import settings
    
    if not next_url:
        return reverse('audits:dashboard')
    
    # Don't allow protocol-relative URLs
    if next_url.startswith('//'):
        return reverse('audits:dashboard')
    
    # Parse URL
    parsed = urlparse(next_url)
    
    # Allow relative URLs only
    if parsed.netloc:
        # This is an absolute URL - check if it's allowed
        allowed = allowed_hosts or settings.ALLOWED_HOSTS
        if parsed.netloc not in allowed:
            log_security_event(
                'OPEN_REDIRECT_ATTEMPT',
                request.user,
                f"Attempted redirect to: {parsed.netloc}",
                severity='WARNING'
            )
            return reverse('audits:dashboard')
    
    return next_url


# Middleware classes

class SecurityLoggingMiddleware:
    """Middleware to log security-relevant events."""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.protected_paths = ['/admin/', '/accounts/login/', '/accounts/logout/']
    
    def __call__(self, request):
        # Log failed authentication attempts
        if request.path in self.protected_paths and request.method == 'POST':
            response = self.get_response(request)
            
            if request.path == '/accounts/login/' and response.status_code in [401, 403]:
                ip = get_client_ip(request)
                log_security_event(
                    'FAILED_LOGIN_ATTEMPT',
                    None,
                    f"IP: {ip}, Username: {request.POST.get('username', 'unknown')}",
                    severity='WARNING'
                )
        else:
            response = self.get_response(request)
        
        return response


class SecurityHeadersMiddleware:
    """Middleware to add additional security headers."""
    
    def __init__(self, get_response):
        self.get_response = get_response
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Remove server identification
        response['Server'] = 'SecurityServer'
        
        # Prevent MIME type sniffing
        response['X-Content-Type-Options'] = 'nosniff'
        
        # Prevent clickjacking
        response['X-Frame-Options'] = 'DENY'
        
        # Enable XSS protection
        response['X-XSS-Protection'] = '1; mode=block'
        
        # Referrer policy
        response['Referrer-Policy'] = 'same-origin'
        
        return response
