"""Configuration validation tests."""

import pytest

from commitverse_hub.config import Settings


def test_settings_load_environment_values() -> None:
    settings = Settings.from_environment(
        {
            "HUB_APPLICATION_NAME": " Local Hub ",
            "HUB_API_VERSION": "1.2.3",
            "HUB_ENVIRONMENT": "testing",
            "HUB_DEBUG": "true",
            "HUB_LOG_LEVEL": "debug",
            "HUB_API_PREFIX": "/custom/v1",
        }
    )

    assert settings.application_name == "Local Hub"
    assert settings.api_version == "1.2.3"
    assert settings.environment == "testing"
    assert settings.debug
    assert settings.log_level == "DEBUG"
    assert settings.api_prefix == "/custom/v1"


@pytest.mark.parametrize(
    ("values", "message"),
    [
        ({"HUB_ENVIRONMENT": "staging"}, "environment"),
        ({"HUB_DEBUG": "sometimes"}, "HUB_DEBUG"),
        ({"HUB_LOG_LEVEL": "TRACE"}, "log_level"),
        ({"HUB_API_PREFIX": "api/v1"}, "api_prefix"),
        ({"HUB_API_PREFIX": "/api/v1/"}, "api_prefix"),
        ({"HUB_API_VERSION": "latest"}, "api_version"),
        ({"HUB_ENVIRONMENT": "production", "HUB_DEBUG": "true"}, "production"),
    ],
)
def test_invalid_environment_configuration_is_rejected(
    values: dict[str, str], message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        Settings.from_environment(values)


def test_default_settings_are_safe() -> None:
    settings = Settings.from_environment({})

    assert settings.environment == "development"
    assert not settings.debug
    assert settings.api_prefix == "/api/v1"
