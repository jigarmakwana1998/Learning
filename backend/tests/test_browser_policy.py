import socket

import pytest

from app.browser.policy import UrlPolicyError, validate_public_https_url


def resolver_for(*addresses: str):
    def resolve(_host, port, *, type):
        family = socket.AF_INET6 if any(":" in address for address in addresses) else socket.AF_INET
        return [(family, type, 6, "", (address, port)) for address in addresses]

    return resolve


def test_normalizes_public_https_url_and_removes_fragment():
    result = validate_public_https_url(
        "HTTPS://Example.COM:443/docs?q=1#private-fragment",
        resolver=resolver_for("93.184.216.34"),
    )
    assert result == "https://example.com/docs?q=1"


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://user:password@example.com",
        "https://example.com:8443",
        "https://127.0.0.1",
        "https://[::1]",
        "https://localhost",
        "https://service.local",
        "https://metadata.google.internal",
    ],
)
def test_rejects_unsafe_url_shapes(url):
    with pytest.raises(UrlPolicyError):
        validate_public_https_url(url, resolver=resolver_for("93.184.216.34"))


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "224.0.0.1",
        "0.0.0.0",
        "::1",
        "fc00::1",
        "fe80::1",
        "ff02::1",
    ],
)
def test_rejects_every_non_public_dns_answer(address):
    with pytest.raises(UrlPolicyError, match="non-public"):
        validate_public_https_url("https://example.com", resolver=resolver_for(address))


def test_rejects_mixed_public_and_private_dns_answers():
    with pytest.raises(UrlPolicyError, match="non-public"):
        validate_public_https_url(
            "https://example.com",
            resolver=resolver_for("93.184.216.34", "10.0.0.1"),
        )


def test_rejects_dns_failure():
    def failing_resolver(*_args, **_kwargs):
        raise socket.gaierror("not found")

    with pytest.raises(UrlPolicyError, match="resolved"):
        validate_public_https_url("https://does-not-exist.example", resolver=failing_resolver)
