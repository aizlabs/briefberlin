"""Tests for config loading and environment overrides."""


from scripts.config import apply_env_overrides


def _base_alerts_dict():
    """Minimal alerts structure matching base.yaml."""
    return {
        "enabled": False,
        "email": "your@email.com",
        "cooldown_hours": 6,
        "email_config": {
            "from": "bot@autospanish.com",
            "smtp": {
                "host": "smtp.gmail.com",
                "port": 587,
                "username": "",
                "password": "",
            },
        },
        "telegram": {
            "enabled": False,
            "bot_token": None,
            "chat_id": None,
        },
    }


def test_alert_email_override(monkeypatch):
    """ALERT_EMAIL sets alerts.email."""
    monkeypatch.setenv("ALERT_EMAIL", "alerts@example.com")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        assert config["alerts"]["email"] == "alerts@example.com"
    finally:
        monkeypatch.delenv("ALERT_EMAIL", raising=False)


def test_audio_env_overrides(monkeypatch):
    """Audio-related env vars populate the audio config subtree."""
    monkeypatch.setenv("AUDIO_ENABLED", "true")
    monkeypatch.setenv("AUDIO_PROVIDER", "elevenlabs")
    monkeypatch.setenv("AUDIO_VOICE", "newsreader")
    monkeypatch.setenv("AUDIO_FORMAT", "mp3")
    monkeypatch.setenv("AUDIO_UPLOAD_ENABLED", "false")
    monkeypatch.setenv("AUDIO_PUBLIC_BASE_URL", "https://media.spaili.com")
    monkeypatch.setenv("AUDIO_S3_BUCKET", "spaili-audio-prod")
    monkeypatch.setenv("AUDIO_S3_REGION", "eu-central-1")
    monkeypatch.setenv("AUDIO_S3_PREFIX", "articles")
    try:
        config = {}
        apply_env_overrides(config)
        assert config["audio"]["enabled"] is True
        assert config["audio"]["provider"] == "elevenlabs"
        assert config["audio"]["voice"] == "newsreader"
        assert config["audio"]["format"] == "mp3"
        assert config["audio"]["upload_enabled"] is False
        assert config["audio"]["public_base_url"] == "https://media.spaili.com"
        assert config["audio"]["s3"]["bucket"] == "spaili-audio-prod"
        assert config["audio"]["s3"]["region"] == "eu-central-1"
        assert config["audio"]["s3"]["prefix"] == "articles"
    finally:
        for key in (
            "AUDIO_ENABLED",
            "AUDIO_PROVIDER",
            "AUDIO_VOICE",
            "AUDIO_FORMAT",
            "AUDIO_UPLOAD_ENABLED",
            "AUDIO_PUBLIC_BASE_URL",
            "AUDIO_S3_BUCKET",
            "AUDIO_S3_REGION",
            "AUDIO_S3_PREFIX",
        ):
            monkeypatch.delenv(key, raising=False)


def test_glossary_env_overrides(monkeypatch):
    """Glossary-related env vars populate the glossary config subtree."""
    monkeypatch.setenv("GLOSSARY_RETRY_ON_EMPTY", "false")
    monkeypatch.setenv("GLOSSARY_DEBUG_DUMP", "true")
    try:
        config = {}
        apply_env_overrides(config)
        assert config["glossary"]["retry_on_empty"] is False
        assert config["glossary"]["debug_dump"] is True
    finally:
        monkeypatch.delenv("GLOSSARY_RETRY_ON_EMPTY", raising=False)
        monkeypatch.delenv("GLOSSARY_DEBUG_DUMP", raising=False)


def test_alerts_enabled_true(monkeypatch):
    """ALERTS_ENABLED=true sets alerts.enabled to True."""
    monkeypatch.setenv("ALERTS_ENABLED", "true")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        assert config["alerts"]["enabled"] is True
    finally:
        monkeypatch.delenv("ALERTS_ENABLED", raising=False)


def test_alerts_enabled_true_case_insensitive(monkeypatch):
    """ALERTS_ENABLED=True (capitalized) still enables alerts."""
    monkeypatch.setenv("ALERTS_ENABLED", "True")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        assert config["alerts"]["enabled"] is True
    finally:
        monkeypatch.delenv("ALERTS_ENABLED", raising=False)


def test_alerts_enabled_false_overrides_yaml(monkeypatch):
    """ALERTS_ENABLED=false sets alerts.enabled to False, overriding YAML that had enabled: true."""
    monkeypatch.setenv("ALERTS_ENABLED", "false")
    try:
        config = {"alerts": {**_base_alerts_dict(), "enabled": True}}
        apply_env_overrides(config)
        assert config["alerts"]["enabled"] is False
    finally:
        monkeypatch.delenv("ALERTS_ENABLED", raising=False)


def test_alerts_enabled_unset_unchanged(monkeypatch):
    """When ALERTS_ENABLED is unset, alerts.enabled is unchanged."""
    monkeypatch.delenv("ALERTS_ENABLED", raising=False)
    config = {"alerts": _base_alerts_dict()}
    apply_env_overrides(config)
    assert config["alerts"]["enabled"] is False


def test_smtp_env_overrides(monkeypatch):
    """ALERT_SMTP_* and fallbacks set email_config.smtp."""
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.sendgrid.net")
    monkeypatch.setenv("ALERT_SMTP_PORT", "2525")
    monkeypatch.setenv("ALERT_SMTP_USERNAME", "apikey")
    monkeypatch.setenv("ALERT_SMTP_PASSWORD", "secret")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        smtp = config["alerts"]["email_config"]["smtp"]
        assert smtp["host"] == "smtp.sendgrid.net"
        assert smtp["port"] == 2525
        assert smtp["username"] == "apikey"
        assert smtp["password"] == "secret"
    finally:
        for key in ("ALERT_SMTP_HOST", "ALERT_SMTP_PORT", "ALERT_SMTP_USERNAME", "ALERT_SMTP_PASSWORD"):
            monkeypatch.delenv(key, raising=False)


def test_smtp_fallback_username_password(monkeypatch):
    """EMAIL_USERNAME and EMAIL_PASSWORD used when ALERT_SMTP_* not set."""
    monkeypatch.setenv("EMAIL_USERNAME", "user@gmail.com")
    monkeypatch.setenv("EMAIL_PASSWORD", "app-pass")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        smtp = config["alerts"]["email_config"]["smtp"]
        assert smtp["username"] == "user@gmail.com"
        assert smtp["password"] == "app-pass"
    finally:
        monkeypatch.delenv("EMAIL_USERNAME", raising=False)
        monkeypatch.delenv("EMAIL_PASSWORD", raising=False)


def test_alert_sender_override(monkeypatch):
    """ALERT_SENDER sets email_config.from."""
    monkeypatch.setenv("ALERT_SENDER", "Bot <noreply@example.com>")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        assert config["alerts"]["email_config"]["from"] == "Bot <noreply@example.com>"
    finally:
        monkeypatch.delenv("ALERT_SENDER", raising=False)


def test_smtp_unset_preserves_yaml(monkeypatch):
    """When SMTP env vars are unset, existing email_config from YAML is unchanged."""
    monkeypatch.delenv("ALERT_SMTP_HOST", raising=False)
    monkeypatch.delenv("ALERT_SMTP_PORT", raising=False)
    monkeypatch.delenv("ALERT_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("ALERT_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_USERNAME", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    config = {"alerts": _base_alerts_dict()}
    apply_env_overrides(config)
    smtp = config["alerts"]["email_config"]["smtp"]
    assert smtp["host"] == "smtp.gmail.com"
    assert smtp["port"] == 587
    assert smtp["username"] == ""
    assert smtp["password"] == ""


def test_smtp_port_invalid_skipped(monkeypatch):
    """Invalid ALERT_SMTP_PORT does not crash; port override is skipped."""
    monkeypatch.setenv("ALERT_SMTP_PORT", "not_a_number")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        # Port remains YAML default
        assert config["alerts"]["email_config"]["smtp"]["port"] == 587
    finally:
        monkeypatch.delenv("ALERT_SMTP_PORT", raising=False)


def test_alerts_section_created_when_missing(monkeypatch):
    """When only ALERT_EMAIL is set, alerts dict is created if missing."""
    monkeypatch.setenv("ALERT_EMAIL", "new@example.com")
    try:
        config = {}
        apply_env_overrides(config)
        assert "alerts" in config
        assert config["alerts"]["email"] == "new@example.com"
    finally:
        monkeypatch.delenv("ALERT_EMAIL", raising=False)


def test_email_config_null_normalized_when_smtp_env_set(monkeypatch):
    """When alerts.email_config is null but an SMTP env var is set, it is normalized to a dict so overrides do not raise."""
    monkeypatch.setenv("ALERT_SMTP_HOST", "smtp.example.com")
    try:
        config = {
            "alerts": {
                "enabled": False,
                "email": "you@example.com",
                "cooldown_hours": 6,
                "email_config": None,
            },
        }
        apply_env_overrides(config)
        assert config["alerts"]["email_config"] is not None
        assert config["alerts"]["email_config"]["smtp"]["host"] == "smtp.example.com"
    finally:
        monkeypatch.delenv("ALERT_SMTP_HOST", raising=False)


def test_email_config_unchanged_when_no_smtp_env(monkeypatch):
    """When no SMTP-related env vars are set, email_config is not created or overwritten (guard in alerts.py preserved)."""
    monkeypatch.delenv("ALERT_SENDER", raising=False)
    monkeypatch.delenv("ALERT_SMTP_HOST", raising=False)
    monkeypatch.delenv("ALERT_SMTP_PORT", raising=False)
    monkeypatch.delenv("ALERT_SMTP_USERNAME", raising=False)
    monkeypatch.delenv("ALERT_SMTP_PASSWORD", raising=False)
    monkeypatch.delenv("EMAIL_USERNAME", raising=False)
    monkeypatch.delenv("EMAIL_PASSWORD", raising=False)
    config = {"alerts": {"enabled": False, "email": "y@example.com", "cooldown_hours": 6}}
    apply_env_overrides(config)
    assert "email_config" not in config["alerts"]


def test_telegram_env_overrides_enable_telegram_and_alerts(monkeypatch):
    """Telegram secrets enable Telegram delivery and global alerts by default."""
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "-1001234567890")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        telegram = config["alerts"]["telegram"]
        assert telegram["bot_token"] == "bot-token"
        assert telegram["chat_id"] == "-1001234567890"
        assert telegram["enabled"] is True
        assert config["alerts"]["enabled"] is True
    finally:
        monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)


def test_telegram_env_does_not_enable_when_incomplete(monkeypatch):
    """A partial Telegram secret set should not auto-enable Telegram delivery."""
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "bot-token")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        telegram = config["alerts"]["telegram"]
        assert telegram["bot_token"] == "bot-token"
        assert telegram["enabled"] is False
        assert config["alerts"]["enabled"] is False
    finally:
        monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)


def test_telegram_env_respects_explicit_alerts_disabled(monkeypatch):
    """ALERTS_ENABLED=false should still suppress all alert delivery."""
    monkeypatch.setenv("ALERTS_ENABLED", "false")
    monkeypatch.setenv("ALERT_TELEGRAM_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("ALERT_TELEGRAM_CHAT_ID", "chat-id")
    try:
        config = {"alerts": _base_alerts_dict()}
        apply_env_overrides(config)
        telegram = config["alerts"]["telegram"]
        assert telegram["enabled"] is True
        assert config["alerts"]["enabled"] is False
    finally:
        monkeypatch.delenv("ALERTS_ENABLED", raising=False)
        monkeypatch.delenv("ALERT_TELEGRAM_BOT_TOKEN", raising=False)
        monkeypatch.delenv("ALERT_TELEGRAM_CHAT_ID", raising=False)
