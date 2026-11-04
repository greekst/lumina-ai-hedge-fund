"""Hard rule 2: the secret scanner must catch known key formats and env-var values."""
import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "check_no_secrets", os.path.join(os.path.dirname(__file__), "..", "scripts", "check_no_secrets.py"))
cns = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cns)


def test_detects_known_formats():
    fake_google = "AIza" + "B" * 35
    assert cns.scan_text("x.py", f'key = "{fake_google}"', [])
    assert cns.scan_text("x.py", "-----BEGIN RSA PRIVATE KEY-----", [])
    assert cns.scan_text("x.py", "ghp_" + "a" * 36, [])


def test_detects_env_value_of_any_format():
    assert cns.scan_text("x.md", "token is zz-123456789-abcdef", [("MY_API_KEY", "zz-123456789-abcdef")])


def test_no_false_positive_on_prose():
    assert not cns.scan_text("doc.md", "risk-sentinel--execution-safety-layer and api_key = os.getenv('X')", [])


def test_repository_is_clean():
    # scans every tracked file with this process's real secret env values
    assert cns.main(["--all"]) == 0


def test_detects_sec_user_agent_value(monkeypatch):
    """Session 2 rule: the owner's SEC contact string must never land in a tracked file."""
    fake = "Jane Researcher jane.researcher@example.org"
    monkeypatch.setenv("SEC_USER_AGENT", fake)
    env = cns._env_secret_values()
    assert cns.scan_text("results/x.md", f"UA was {fake}", env)
    assert cns.scan_text("LOG.md", "contact: jane.researcher@example.org", env)  # the e-mail part alone
    assert not cns.scan_text("LOG.md", "SEC_USER_AGENT is read from the environment only", env)
