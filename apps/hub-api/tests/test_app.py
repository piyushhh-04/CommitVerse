"""Application factory tests."""

from commitverse_hub.config import Settings
from commitverse_hub.main import create_app


def test_application_factory_uses_supplied_settings() -> None:
    settings = Settings(
        application_name="Test Hub",
        api_version="2.3.4",
        environment="testing",
        api_prefix="/test/v1",
    )

    app = create_app(settings)

    assert app.title == "Test Hub"
    assert app.version == "2.3.4"
    assert "CommitVerse Hub API" in app.description
    assert app.state.settings is settings
    assert not app.debug
