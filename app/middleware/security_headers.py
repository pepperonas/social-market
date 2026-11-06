"""
EDUCATIONAL SECURITY TRAINING ENVIRONMENT
Security Headers Middleware
Purpose: Additional security headers for defense-in-depth
"""

import re
import uuid

# What a request id may look like when it comes from upstream (nginx's
# $request_id is 32 hex characters). Anything else is replaced.
_REQUEST_ID = re.compile(r'^[A-Za-z0-9-]{8,64}$')


class SecurityHeadersMiddleware:
    """
    WSGI middleware for adding security headers
    Complements Flask-Talisman with additional headers
    """

    def __init__(self, app):
        self.app = app

    def __call__(self, environ, start_response):
        """Process request and add security headers to response"""

        # Reuse the upstream request id only if it looks like one. It was taken
        # verbatim from the client header: reflected in a response header and
        # carried into the logs, i.e. a way to write arbitrary text there.
        incoming = environ.get('HTTP_X_REQUEST_ID', '')
        request_id = incoming if _REQUEST_ID.match(incoming) else uuid.uuid4().hex
        # Store in environ so Flask can access it via request.environ
        environ['HTTP_X_REQUEST_ID'] = request_id

        def custom_start_response(status, headers, exc_info=None):
            # Add request ID for tracking
            headers.append(('X-Request-ID', request_id))

            # Add custom security headers
            headers.append(('X-Security-Environment', 'Educational-Training-Only'))

            # Removed: `Access-Control-Allow-Origin: self`. 'self' is not a valid
            # value for that header (it takes an origin or '*'); not sending it
            # is what keeps cross-origin reads blocked. And X-Content-Type-Options
            # came twice -- Flask-Talisman already sets it.

            # Remove server identification
            headers = [(name, value) for name, value in headers
                      if name.lower() not in ['server', 'x-powered-by']]

            return start_response(status, headers, exc_info)

        return self.app(environ, custom_start_response)
