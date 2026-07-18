from app.core.security import decrypt, encrypt, redact


def test_transcript_redacts_and_encrypts_secrets():
    protected = encrypt("api_key=super-secret password: no-leak")
    assert "super-secret" not in protected
    assert decrypt(protected) == "api_key=[REDACTED] password=[REDACTED]"


def test_redact_leaves_normal_content_readable():
    assert redact("learn Python with functions") == "learn Python with functions"
