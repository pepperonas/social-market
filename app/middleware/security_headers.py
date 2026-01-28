"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Security Headers Middleware
Purpose: Additional security headers for defense-in-depth
"""

import uuid


class SecurityHeadersMiddleware:
    """
    WSGI middleware for adding security headers
    Complements Flask-Talisman with additional headers
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        """Process request and add security headers to response"""

        def custom_start_response(status, headers, exc_info=None):
            # Add request ID for tracking
            request_id = str(uuid.uuid4())
            headers.append(('X-Request-ID', request_id))

            # Add custom security headers
            headers.append(('X-Security-Environment', 'Educational-Training-Only'))

            # Additional CORS restrictions
            headers.append(('Access-Control-Allow-Origin', 'self'))

            # Prevent MIME type sniffing
            headers.append(('X-Content-Type-Options', 'nosniff'))

            # Remove server identification
            headers = [(name, value) for name, value in headers
                      if name.lower() not in ['server', 'x-powered-by']]

            return start_response(status, headers, exc_info)

        return self.app(environ, custom_start_response)
