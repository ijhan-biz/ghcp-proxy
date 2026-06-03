import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ghcp_proxy import masking


def test_masks_github_token():
    text = "my token is ghp_abcdefghijklmnopqrstuvwxyz0123456789"
    out, n = masking.mask_text(text)
    assert "ghp_" not in out
    assert "[REDACTED_GITHUB_TOKEN]" in out
    assert n == 1


def test_masks_private_key_block():
    text = (
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc\nlines\n-----END RSA PRIVATE KEY-----"
    )
    out, n = masking.mask_text(text)
    assert "PRIVATE KEY" not in out
    assert n == 1


def test_masks_email_and_aws():
    text = "contact dev@example.com key AKIAIOSFODNN7EXAMPLE done"
    out, n = masking.mask_text(text)
    assert "dev@example.com" not in out
    assert "AKIAIOSFODNN7EXAMPLE" not in out
    assert n >= 2


def test_empty_text():
    out, n = masking.mask_text("")
    assert out == ""
    assert n == 0


def test_clean_text_unchanged():
    text = "def add(a, b):\n    return a + b"
    out, n = masking.mask_text(text)
    assert out == text
    assert n == 0
