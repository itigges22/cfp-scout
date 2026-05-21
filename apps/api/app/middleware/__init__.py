"""ASGI middleware + global exception handlers.

Two pieces:

* :class:`~app.middleware.request_id.RequestIDMiddleware` — propagates a
  unique request id through every log line and surfaces it in the
  ``X-Request-ID`` response header.
* :func:`~app.middleware.error_handler.install_error_handlers` — registers
  RFC 7807 problem+json formatters for unhandled exceptions and validation errors.
"""
