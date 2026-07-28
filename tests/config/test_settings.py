import pytest

from app.config.settings import Settings


@pytest.fixture
def settings_env(monkeypatch):
    monkeypatch.setenv("NFS_SHARE_ROOT_PATH", "/tmp/x")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./t.db")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("production", "prod"),
        ("PRODUCTION", "prod"),
        ("development", "dev"),
        ("testing", "test"),
        ("prod", "prod"),
        ("dev", "dev"),
        ("test", "test"),
    ],
)
def test_environment_normalization(settings_env, monkeypatch, raw, expected):
    monkeypatch.setenv("ENVIRONMENT", raw)
    settings = Settings(_env_file=None)
    assert settings.ENVIRONMENT == expected


def test_environment_invalid_value(settings_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "staging")
    with pytest.raises(ValueError, match="ENVIRONMENT must be one of"):
        Settings(_env_file=None)


def test_production_alias_sets_debug_false(settings_env, monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    settings = Settings(_env_file=None)
    assert settings.ENVIRONMENT == "prod"
    assert settings.DEBUG is False
