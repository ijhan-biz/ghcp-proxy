import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from ghcp_proxy.config import load_config, Config


def test_default_config_loads():
    cfg = load_config()
    assert cfg.storage.db_path
    assert cfg.allowlist_hosts


def test_host_allowed_exact():
    cfg = Config(allowlist_hosts=["api.githubcopilot.com"])
    assert cfg.host_allowed("api.githubcopilot.com")
    assert not cfg.host_allowed("evil.com")


def test_host_allowed_wildcard_suffix():
    cfg = Config(allowlist_hosts=[".githubcopilot.com"])
    assert cfg.host_allowed("foo.githubcopilot.com")
    assert cfg.host_allowed("githubcopilot.com")
    assert not cfg.host_allowed("githubcopilot.com.evil.com")


def test_host_allowed_case_insensitive():
    cfg = Config(allowlist_hosts=["api.githubcopilot.com"])
    assert cfg.host_allowed("API.GitHubCopilot.com")
