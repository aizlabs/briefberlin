import logging
from pathlib import Path
from types import SimpleNamespace

from scripts.alerts import AlertManager
from scripts.models import AlertsConfig, EmailConfig, SMTPConfig, TelegramConfig


class DummySMTP:
    last_instance = None

    def __init__(self, *args, **kwargs):
        self.closed = False

    def __enter__(self):
        DummySMTP.last_instance = self
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def starttls(self):
        raise RuntimeError("starttls failure")

    def login(self, *args, **kwargs):
        return None

    def send_message(self, *args, **kwargs):
        return None


def test_send_email_closes_connection_on_failure(monkeypatch):
    monkeypatch.setattr("smtplib.SMTP", DummySMTP)

    alerts_config = AlertsConfig(
        enabled=True,
        email="recipient@example.com",
        email_config=EmailConfig(
            from_email="sender@example.com",
            smtp=SMTPConfig(host="smtp.example.com", port=587, username="user", password="pass"),
        ),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    alert_manager._send_email(subject="Test", body="Body", priority="high")

    assert DummySMTP.last_instance is not None
    assert DummySMTP.last_instance.closed is True


def test_send_error_does_not_raise_when_cooldown_save_fails(monkeypatch, tmp_path, caplog):
    def failing_open(self, *args, **kwargs):  # noqa: ANN001, ANN002
        raise OSError("write failure")

    alerts_config = AlertsConfig(
        enabled=True,
        email="recipient@example.com",
        email_config=EmailConfig(
            from_email="sender@example.com",
            smtp=SMTPConfig(host="smtp.example.com", port=587),
        ),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={"file": str(tmp_path / "alerts.log")})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "_send_email", lambda *_, **__: None)
    monkeypatch.setattr(Path, "open", failing_open)

    caplog.set_level(logging.ERROR)

    alert_manager.send_error("Failure sending alert")

    assert any("Failed to persist alert cooldowns" in record.getMessage() for record in caplog.records)


def test_send_failure_alert_sends_email(monkeypatch):
    captured = {}

    def fake_send_email(*, subject, body, priority="normal"):
        captured["subject"] = subject
        captured["body"] = body
        captured["priority"] = priority

    alerts_config = AlertsConfig(
        enabled=True,
        email="recipient@example.com",
        email_config=EmailConfig(
            from_email="sender@example.com",
            smtp=SMTPConfig(host="smtp.example.com", port=587),
        ),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "_send_email", staticmethod(fake_send_email))

    alert_manager.send_failure_alert(
        run_id="run-123",
        environment="production",
        stage="synthesis",
        exception=ValueError("bad json"),
    )

    assert captured["priority"] == "high"
    assert "run-123" in captured["subject"]
    assert "Traceback:" in captured["body"]


def test_send_failure_alert_sends_telegram(monkeypatch):
    captured = {}

    def fake_send_telegram(self, message):
        captured["message"] = message

    alerts_config = AlertsConfig(
        enabled=True,
        telegram=TelegramConfig(enabled=True, bot_token="token", chat_id="chat-id"),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "send_telegram", fake_send_telegram)

    alert_manager.send_failure_alert(
        run_id="run-123",
        environment="production",
        stage="synthesis",
        exception=ValueError("bad json"),
    )

    assert "run-123" in captured["message"]
    assert "Pipeline failure" in captured["message"]
    assert "Traceback:" in captured["message"]


def test_send_success_summary_sends_email_when_enabled(monkeypatch):
    captured = {}

    def fake_send_email(self, *, subject, body, priority="normal"):
        captured["subject"] = subject
        captured["body"] = body
        captured["priority"] = priority

    alerts_config = AlertsConfig(
        enabled=True,
        email="recipient@example.com",
        email_config=EmailConfig(
            from_email="sender@example.com",
            smtp=SMTPConfig(host="smtp.example.com", port=587),
        ),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "_send_email", fake_send_email)

    alert_manager.send_success_summary(
        run_id="run-456",
        duration_seconds=120.5,
        attempted=3,
        published=2,
        rejected=1,
        regenerations=1,
        published_articles=[("Article One", "A2"), ("Article Two", "B1")],
    )

    assert captured["priority"] == "normal"
    assert "generation success" in captured["subject"]
    assert "2 article(s)" in captured["subject"]
    assert "run-456" in captured["body"]
    assert "120" in captured["body"]
    assert "2 published" in captured["body"]
    assert "A2" in captured["body"] and "B1" in captured["body"]
    assert "[A2] Article One" in captured["body"]
    assert "[B1] Article Two" in captured["body"]


def test_send_success_summary_sends_telegram_when_enabled(monkeypatch):
    captured = {}

    def fake_send_telegram(self, message):
        captured["message"] = message

    alerts_config = AlertsConfig(
        enabled=True,
        telegram=TelegramConfig(enabled=True, bot_token="token", chat_id="chat-id"),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "send_telegram", fake_send_telegram)

    alert_manager.send_success_summary(
        run_id="run-456",
        duration_seconds=120.5,
        attempted=3,
        published=2,
        rejected=1,
        regenerations=1,
        published_articles=[("Article One", "A2"), ("Article Two", "B1")],
    )

    assert "generation success" in captured["message"]
    assert "run-456" in captured["message"]
    assert "[A2] Article One" in captured["message"]
    assert "[B1] Article Two" in captured["message"]


def test_send_success_summary_does_not_send_when_published_zero(monkeypatch):
    sent = []

    def capture_send(self, *, subject, body, priority="normal"):
        sent.append((subject, body))

    alerts_config = AlertsConfig(
        enabled=True,
        email="recipient@example.com",
        email_config=EmailConfig(
            from_email="sender@example.com",
            smtp=SMTPConfig(host="smtp.example.com", port=587),
        ),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "_send_email", capture_send)

    alert_manager.send_success_summary(
        run_id="run-789",
        duration_seconds=60.0,
        attempted=2,
        published=0,
        rejected=2,
        regenerations=0,
        published_articles=[],
    )

    assert len(sent) == 0


def test_send_success_summary_does_not_send_when_alerts_disabled(monkeypatch, caplog):
    sent = []

    def capture_send(self, *, subject, body, priority="normal"):
        sent.append((subject, body))

    alerts_config = AlertsConfig(
        enabled=False,
        email="recipient@example.com",
        email_config=EmailConfig(
            from_email="sender@example.com",
            smtp=SMTPConfig(host="smtp.example.com", port=587),
        ),
    )
    config = SimpleNamespace(alerts=alerts_config, logging={})
    alert_manager = AlertManager(config=config, logger=logging.getLogger("alerts-test"))

    monkeypatch.setattr(AlertManager, "_send_email", capture_send)

    alert_manager.send_success_summary(
        run_id="run-999",
        duration_seconds=90.0,
        attempted=1,
        published=1,
        rejected=0,
        regenerations=0,
        published_articles=[("Only Article", "A2")],
    )

    assert len(sent) == 0
    assert any("Alert delivery is disabled" in record.getMessage() for record in caplog.records)
