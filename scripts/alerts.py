"""Alert management utilities for pipeline errors and notifications."""

from __future__ import annotations

import json
import logging
import smtplib
import traceback
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, Optional, Sequence, Tuple

from scripts.config import AppConfig
from scripts.models import AlertsConfig


class AlertManager:
    """Send alerts via email (and optional Telegram) with cooldown support."""

    def __init__(self, config: AppConfig, logger: logging.Logger):
        self.logger = logger
        self.alerts_config: AlertsConfig = config.alerts
        self.enabled = bool(self.alerts_config.enabled)

        log_file = config.logging.get("file") if isinstance(config.logging, dict) else None
        default_cooldown_path = Path("output/logs/alert_cooldown.json")
        self.cooldown_file = Path(log_file).parent / "alert_cooldown.json" if log_file else default_cooldown_path
        self.cooldown_hours = self.alerts_config.cooldown_hours
        self.cooldowns = self._load_cooldowns()

    def _load_cooldowns(self) -> Dict[str, str]:
        if not self.cooldown_file.exists():
            return {}

        try:
            with self.cooldown_file.open("r", encoding="utf-8") as file:
                return json.load(file)
        except Exception:
            return {}

    def _save_cooldowns(self) -> None:
        try:
            self.cooldown_file.parent.mkdir(parents=True, exist_ok=True)
            with self.cooldown_file.open("w", encoding="utf-8") as file:
                json.dump(self.cooldowns, file, indent=2)
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Failed to persist alert cooldowns",
                exc_info=(exc.__class__, exc, exc.__traceback__),
            )

    def _check_cooldown(self, alert_key: str) -> bool:
        if alert_key not in self.cooldowns:
            return False

        last_sent = datetime.fromisoformat(self.cooldowns[alert_key])
        cooldown_until = last_sent + timedelta(hours=self.cooldown_hours)
        return datetime.utcnow() < cooldown_until

    def _update_cooldown(self, alert_key: str) -> None:
        self.cooldowns[alert_key] = datetime.utcnow().isoformat()
        self._save_cooldowns()

    def send_critical(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Send a critical alert (bypasses cooldown)."""

        self.logger.critical(message, extra=context or {})
        if not self.enabled:
            self.logger.warning("Alert delivery is disabled; not sending email.")
            return

        subject = f"🚨 CRITICAL: BriefBerlin - {message}"
        body = self._format_alert_body(message, context, "CRITICAL")
        self._send_email(subject=subject, body=body, priority="high")
        self._send_telegram_alert(subject=subject, body=body)

    def send_failure_alert(
        self,
        *,
        run_id: str,
        environment: str,
        stage: str,
        exception: Exception,
    ) -> None:
        """Send a structured failure notification to operators (bypasses cooldown)."""

        message = "Pipeline failure"
        context = {
            "run_id": run_id,
            "environment": environment,
            "stage": stage or "unknown",
            "exception": str(exception),
        }
        self.logger.error(message, extra=context)
        if not self.enabled:
            self.logger.warning("Alert delivery is disabled; not sending email.")
            return

        traceback_text = "".join(traceback.format_exception(exception)).strip()
        body = (
            self._format_alert_body(message, context, "ERROR")
            + "\n\nTraceback:\n"
            + traceback_text
        )
        subject = f"❌ ERROR: BriefBerlin - {message} ({environment}) - {run_id}"
        self._send_email(subject=subject, body=body, priority="high")
        self._send_telegram_alert(subject=subject, body=body)

    def send_error(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Send an error alert (respects cooldown)."""

        alert_key = f"error:{message[:50]}"
        self.logger.error(message, extra=context or {})

        if not self.enabled:
            self.logger.warning("Alert delivery is disabled; not sending email.")
            return
        if self._check_cooldown(alert_key):
            return

        subject = f"❌ ERROR: BriefBerlin - {message}"
        body = self._format_alert_body(message, context, "ERROR")
        self._send_email(subject=subject, body=body)
        self._send_telegram_alert(subject=subject, body=body)
        self._update_cooldown(alert_key)

    def send_warning(self, message: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Send a warning alert (currently logged only, cooldown respected)."""

        alert_key = f"warning:{message[:50]}"
        self.logger.warning(message, extra=context or {})

        if not self.enabled or self._check_cooldown(alert_key):
            return

        self._update_cooldown(alert_key)

    def send_success_summary(
        self,
        *,
        run_id: str,
        duration_seconds: float,
        attempted: int,
        published: int,
        rejected: int,
        regenerations: int,
        published_articles: Sequence[Tuple[str, str]],
    ) -> None:
        """Send a short success email when the pipeline published at least one article."""

        if published == 0:
            return

        if not self.enabled:
            self.logger.warning("Alert delivery is disabled; not sending email.")
            return

        levels_str = ", ".join(sorted({level for _title, level in published_articles}))
        body_lines = [
            "BriefBerlin – generation success",
            "",
            f"Run: {run_id} | Duration: {duration_seconds:.0f}s",
            f"Articles: {published} published (from {attempted} attempts, {rejected} rejected, {regenerations} regenerations)",
            f"Levels: {levels_str}",
            "",
            "Titles:",
        ]
        for title, level in published_articles:
            body_lines.append(f"  - [{level}] {title}")
        body_lines.append("")
        body_lines.append("---")
        body_lines.append("BriefBerlin Alert System")
        body = "\n".join(body_lines)

        subject = f"BriefBerlin – generation success – {published} article(s)"
        self._send_email(subject=subject, body=body, priority="normal")
        self._send_telegram_alert(subject=subject, body=body)

    def _format_alert_body(self, message: str, context: Optional[Dict[str, Any]], severity: str) -> str:
        body = (
            "BriefBerlin Alert\n\n"
            f"Severity: {severity}\n"
            f"Time: {datetime.utcnow().isoformat()}Z\n"
            f"Message: {message}\n\n"
        )

        if context:
            body += "Context:\n"
            for key, value in context.items():
                body += f"  {key}: {value}\n"

        body += "\n---\nBriefBerlin Alert System"
        return body

    def _send_email(self, subject: str, body: str, priority: str = "normal") -> None:
        email_config = self.alerts_config.email_config
        to_email = self.alerts_config.email

        if not to_email or not email_config:
            self.logger.warning("Alert email not configured, skipping email send")
            return

        self.logger.info("Sending alert email to %s", to_email)
        smtp_config = email_config.smtp
        username = smtp_config.username
        password = smtp_config.password

        smtp_log_context = {
            "smtp_host": smtp_config.host,
            "smtp_port": smtp_config.port,
            "smtp_username": username,
            "from_email": email_config.from_email,
            "to_email": to_email,
            "alerts_enabled": self.enabled,
        }

        try:
            message = MIMEMultipart()
            message["From"] = email_config.from_email
            message["To"] = to_email
            message["Subject"] = subject

            if priority == "high":
                message["X-Priority"] = "1"

            message.attach(MIMEText(body, "plain"))

            self.logger.info("Alert email SMTP config", extra=smtp_log_context)

            with smtplib.SMTP(smtp_config.host, smtp_config.port) as server:
                server.starttls()

                if username and password:
                    server.login(username, password)

                server.send_message(message)

            self.logger.info("Alert email sent", extra={"subject": subject, **smtp_log_context})
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Failed to send alert email",
                extra=smtp_log_context,
                exc_info=(exc.__class__, exc, exc.__traceback__),
            )

    def _send_telegram_alert(self, subject: str, body: str) -> None:
        self.send_telegram(f"{subject}\n\n{body}")

    def send_telegram(self, message: str) -> None:
        telegram_config = self.alerts_config.telegram

        if not telegram_config or not telegram_config.enabled:
            return

        bot_token = telegram_config.bot_token
        chat_id = telegram_config.chat_id

        if not bot_token or not chat_id:
            return

        try:
            import requests

            url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
            data = {"chat_id": chat_id, "text": message}

            response = requests.post(url, json=data, timeout=10)
            response.raise_for_status()

            self.logger.info("Telegram alert sent")
        except Exception as exc:  # noqa: BLE001
            self.logger.error(
                "Failed to send Telegram alert",
                exc_info=(exc.__class__, exc, exc.__traceback__),
            )
