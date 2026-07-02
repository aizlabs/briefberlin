"""
Logging System

Environment-aware logging:
- Local: Colored console output + file
- Production: JSON structured logging + file
"""

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_LOGGER_NAME = "briefberlin"


class JSONFormatter(logging.Formatter):
    """JSON formatter for structured logging in production"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'level': record.levelname,
            'message': record.getMessage(),
            'component': record.name,
        }

        # Add extra fields if present
        if hasattr(record, 'run_id'):
            log_data['run_id'] = record.run_id

        if hasattr(record, 'topic_id'):
            log_data['topic_id'] = record.topic_id

        if hasattr(record, 'duration_ms'):
            log_data['duration_ms'] = record.duration_ms

        # Add any other extra attributes
        for key, value in record.__dict__.items():
            if key not in ['name', 'msg', 'args', 'created', 'filename', 'funcName',
                          'levelname', 'levelno', 'lineno', 'module', 'msecs',
                          'message', 'pathname', 'process', 'processName',
                          'relativeCreated', 'thread', 'threadName', 'exc_info',
                          'exc_text', 'stack_info', 'run_id', 'topic_id', 'duration_ms']:
                log_data[key] = value

        # Add exception info if present
        if record.exc_info:
            log_data['exception'] = self.formatException(record.exc_info)

        return json.dumps(log_data, ensure_ascii=False)


class RunIDFilter(logging.Filter):
    """Filter to add run_id to log records without global state"""

    def __init__(self, run_id: str):
        super().__init__()
        self.run_id = run_id

    def filter(self, record: logging.LogRecord) -> bool:
        record.run_id = self.run_id
        return True


class ColoredFormatter(logging.Formatter):
    """Colored formatter for human-readable local logging"""

    # ANSI color codes
    COLORS = {
        'DEBUG': '\033[36m',    # Cyan
        'INFO': '\033[32m',     # Green
        'WARNING': '\033[33m',  # Yellow
        'ERROR': '\033[31m',    # Red
        'CRITICAL': '\033[35m', # Magenta
    }
    RESET = '\033[0m'
    BOLD = '\033[1m'

    def format(self, record: logging.LogRecord) -> str:
        # Color the level
        level_color = self.COLORS.get(record.levelname, '')
        colored_level = f"{level_color}{record.levelname:8s}{self.RESET}"

        # Format timestamp
        timestamp = datetime.fromtimestamp(record.created).strftime('%H:%M:%S')

        # Build message
        msg = record.getMessage()

        # Add extra context if present
        extras = []
        if hasattr(record, 'level') and record.level:
            extras.append(f"level={record.level}")
        if hasattr(record, 'word_count'):
            extras.append(f"words={record.word_count}")
        if hasattr(record, 'duration_ms'):
            duration_s = record.duration_ms / 1000
            extras.append(f"({duration_s:.1f}s)")

        extra_str = ' '.join(extras)
        if extra_str:
            msg = f"{msg} | {extra_str}"

        # Combine
        return f"[{timestamp}] {colored_level} {self.BOLD}{record.name:20s}{self.RESET} | {msg}"


def setup_logger(config, run_id: str) -> logging.Logger:
    """
    Set up logging based on configuration

    Args:
        config: AppConfig instance or configuration dictionary
        run_id: Unique run identifier

    Returns:
        Configured logger
    """
    # Get logging config (handle both Pydantic model and dict)
    if hasattr(config, 'logging'):
        log_config = config.logging
    elif isinstance(config, dict):
        log_config = config.get('logging', {})
    else:
        log_config = {}

    # Access values (log_config is always a dict)
    logger_name = str(log_config.get('name') or DEFAULT_LOGGER_NAME).strip() or DEFAULT_LOGGER_NAME
    level = getattr(logging, log_config.get('level', 'INFO'))
    format_type = log_config.get('format', 'console')
    log_file = log_config.get('file', 'logs/app.log')

    logger = logging.getLogger(logger_name)
    logger.setLevel(level)
    logger.handlers.clear()  # Remove any existing handlers

    # Create run_id filter that will be added to handlers
    run_id_filter = RunIDFilter(run_id)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(level)
    console_handler.addFilter(run_id_filter)  # Add filter to handler for child loggers

    if format_type == 'json':
        console_handler.setFormatter(JSONFormatter())
    else:
        console_handler.setFormatter(ColoredFormatter())

    logger.addHandler(console_handler)

    # File handler
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path, encoding='utf-8')
    file_handler.setLevel(level)
    file_handler.addFilter(run_id_filter)  # Add filter to handler for child loggers

    if format_type == 'json':
        file_handler.setFormatter(JSONFormatter())
    else:
        # Always use JSON for file in production for easier parsing
        file_handler.setFormatter(JSONFormatter())

    logger.addHandler(file_handler)

    return logger


def get_logger_name(config=None, component: str | None = None) -> str:
    """Return configured base logger name, optionally with a component suffix."""
    log_config = {}
    if config is not None and hasattr(config, 'logging'):
        log_config = config.logging
    elif isinstance(config, dict):
        log_config = config.get('logging', {})

    base_name = str(log_config.get('name') or DEFAULT_LOGGER_NAME).strip() or DEFAULT_LOGGER_NAME
    if not component:
        return base_name
    return f"{base_name}.{component}"


def get_component_logger(name: str, config=None) -> logging.Logger:
    """Get a logger for a specific component"""
    return logging.getLogger(get_logger_name(config, name))
