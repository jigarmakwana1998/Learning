"""Network policy for anonymous, public, read-only browser research."""

from __future__ import annotations

import ipaddress
import socket
from collections.abc import Callable, Iterable
from urllib.parse import SplitResult, urlsplit, urlunsplit


class UrlPolicyError(ValueError):
    """Raised when a URL is outside the public browser research boundary."""


Resolver = Callable[..., Iterable[tuple]]

_BLOCKED_HOSTS = {
    "localhost",
    "localhost.localdomain",
    "instance-data",
    "metadata.google.internal",
    "metadata.aws.internal",
}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".home.arpa")


def validate_public_https_url(url: str, *, resolver: Resolver = socket.getaddrinfo) -> str:
    """Validate and normalize an HTTPS URL whose DNS answers are all public.

    DNS is intentionally resolved on every call. Callers must invoke this function
    immediately before each navigation and again for the final URL after redirects.
    """
    if not isinstance(url, str) or not url.strip():
        raise UrlPolicyError("URL must be a non-empty string")
    if len(url) > 4096:
        raise UrlPolicyError("URL is too long")

    try:
        parsed = urlsplit(url.strip())
        port = parsed.port
    except ValueError as error:
        raise UrlPolicyError("URL is malformed") from error

    if parsed.scheme.casefold() != "https":
        raise UrlPolicyError("Only HTTPS URLs are allowed")
    if not parsed.netloc or not parsed.hostname:
        raise UrlPolicyError("URL must include a hostname")
    if parsed.username is not None or parsed.password is not None:
        raise UrlPolicyError("URL credentials are not allowed")
    if port not in (None, 443):
        raise UrlPolicyError("Only HTTPS port 443 is allowed")

    hostname = _normalize_hostname(parsed.hostname)
    _reject_local_hostname(hostname)
    try:
        ipaddress.ip_address(hostname)
    except ValueError:
        pass
    else:
        raise UrlPolicyError("IP-literal URLs are not allowed")

    try:
        answers = list(resolver(hostname, 443, type=socket.SOCK_STREAM))
    except (OSError, socket.gaierror) as error:
        raise UrlPolicyError("Hostname could not be resolved") from error
    if not answers:
        raise UrlPolicyError("Hostname did not resolve")

    addresses: set[ipaddress.IPv4Address | ipaddress.IPv6Address] = set()
    for answer in answers:
        try:
            addresses.add(ipaddress.ip_address(answer[4][0].split("%", 1)[0]))
        except (IndexError, TypeError, ValueError) as error:
            raise UrlPolicyError("Hostname returned an invalid address") from error
    if not addresses or any(not _is_public(address) for address in addresses):
        raise UrlPolicyError("Hostname resolves to a non-public address")

    normalized = SplitResult(
        scheme="https",
        netloc=hostname,
        path=parsed.path or "/",
        query=parsed.query,
        fragment="",
    )
    return urlunsplit(normalized)


def hostname_for_url(url: str) -> str:
    """Return the normalized hostname from a URL already accepted by the policy."""
    hostname = urlsplit(url).hostname
    if hostname is None:
        raise UrlPolicyError("URL must include a hostname")
    return _normalize_hostname(hostname)


def _normalize_hostname(hostname: str) -> str:
    try:
        normalized = hostname.rstrip(".").encode("idna").decode("ascii").casefold()
    except UnicodeError as error:
        raise UrlPolicyError("Hostname is invalid") from error
    if not normalized or len(normalized) > 253 or any(len(label) > 63 for label in normalized.split(".")):
        raise UrlPolicyError("Hostname is invalid")
    return normalized


def _reject_local_hostname(hostname: str) -> None:
    if hostname in _BLOCKED_HOSTS or hostname.endswith(_BLOCKED_SUFFIXES):
        raise UrlPolicyError("Local and metadata hostnames are not allowed")


def _is_public(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_global
        and not address.is_private
        and not address.is_loopback
        and not address.is_link_local
        and not address.is_multicast
        and not address.is_reserved
        and not address.is_unspecified
    )
