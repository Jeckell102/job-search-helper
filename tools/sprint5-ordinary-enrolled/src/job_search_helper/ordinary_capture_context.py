"""Lexical private sink for one measured direct Rippling observation."""

from contextlib import contextmanager
from contextvars import ContextVar
from hashlib import sha256
import json
import os
import re
from threading import get_ident


_POLICY = {
    'schema': 'ordinary-rippling-direct-capture-policy-v1',
    'provider': 'Rippling',
    'transport': 'job_search_helper.shared_boards.Transport',
    'origin': 'https://ats.rippling.com',
    'method': 'GET', 'page': 0, 'status': 200,
    'proxy': 'disabled', 'redirect': 'disabled',
    'tls': 'verified_compiled_system_ca_paths_no_ambient_overrides',
    'tls_key_logging': 'disabled', 'redirect_indicators': 'refused',
    'body_encoding_request': 'identity',
}
_CAPTURE_POLICY_SHA256 = sha256(json.dumps(_POLICY, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
_CONFIGURED_URL = re.compile(r'https://ats\.rippling\.com/[a-z0-9][a-z0-9-]{0,99}/jobs')
_ACTIVE_CAPTURE = ContextVar('ordinary_direct_rippling_capture', default=None)


def capture_policy_sha256():
    """Return the immutable default direct-capture policy pin for enrollment."""
    return _CAPTURE_POLICY_SHA256


class _DirectCapture:
    def __init__(self, ticket):
        self.ticket = ticket
        self.url = ticket._configured_url
        self.thread = get_ident()
        self.claimed = False

    def matches(self, url):
        ticket = self.ticket
        return (ticket is not None and _ACTIVE_CAPTURE.get() is self and self.thread == get_ident()
                and url == self.url == ticket._configured_url
                and not ('SSL_CERT_FILE' in os.environ or 'SSL_CERT_DIR' in os.environ)
                and not ticket._consumed
                and ticket._slot.reservation.get('capture_policy_sha256') == _CAPTURE_POLICY_SHA256)

    def offer(self, observation, response):
        if self.matches(observation.configured_url):
            self.ticket.offer(observation, request_url=self.url, response_url=response.response_url,
                              status=response.status, body=response.body)


@contextmanager
def bind_direct_capture(ticket):
    """Bind an enrolled ticket only for the synchronous measured fetch."""
    # The ordinary scan path can import this module without the optional raw
    # custody integration. Only its measured caller can bind a real ticket.
    from .ordinary_raw_capture import CaptureTicket

    if (type(ticket) is not CaptureTicket or not isinstance(ticket._configured_url, str)
            or _CONFIGURED_URL.fullmatch(ticket._configured_url) is None
            or ticket._slot.reservation.get('capture_policy_sha256') != _CAPTURE_POLICY_SHA256):
        raise ValueError('Direct Rippling capture requires a measured ticket with the current policy.')
    with ticket._lock:
        if ticket._consumed or ticket._offered or getattr(ticket, '_direct_capture_bound', False):
            raise ValueError('Direct Rippling capture ticket is already used.')
        ticket._direct_capture_bound = True
    binding = _DirectCapture(ticket)
    token = _ACTIVE_CAPTURE.set(binding)
    try:
        yield
    finally:
        # A previously copied context must not extend the ticket's lifetime.
        binding.ticket = None
        _ACTIVE_CAPTURE.reset(token)


def _claim_direct_capture(url):
    binding = _ACTIVE_CAPTURE.get()
    if binding is None or binding.claimed or not binding.matches(url):
        return None
    binding.claimed = True
    return binding
