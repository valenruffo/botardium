import logging
import json
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler
from contextvars import ContextVar, Token
from uuid import uuid4
from typing import Optional


trace_id_var: ContextVar[Optional[str]] = ContextVar('trace_id', default=None)


def generate_trace_id() -> str:
    return str(uuid4())


def setup_logger(name: str, log_dir: str = ".tmp/logs") -> logging.Logger:
    os.makedirs(log_dir, exist_ok=True)
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    if logger.handlers:
        return logger
    
    log_file = os.path.join(log_dir, f"{name}.log")
    
    class JSONFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            log_data = {
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "level": record.levelname,
                "trace_id": trace_id_var.get() or "no-trace-id",
                "logger": record.name,
                "message": record.getMessage(),
                "module": record.module,
                "function": record.funcName,
                "line": record.lineno
            }
            
            if record.exc_info:
                log_data["exception"] = self.formatException(record.exc_info)
            
            extra = {k: v for k, v in record.__dict__.items() 
                    if k not in ('name', 'msg', 'args', 'created', 'filename', 
                                'funcName', 'levelname', 'levelno', 'lineno', 
                                'module', 'msecs', 'message', 'pathname', 'process', 
                                'processName', 'relativeCreated', 'thread', 'threadName', 
                                'exc_info', 'exc_text', 'stack_info')}
            if extra:
                log_data["extra"] = extra
            
            return json.dumps(log_data)
    
    handler = TimedRotatingFileHandler(
        log_file,
        when="midnight",
        interval=1,
        backupCount=30,
        encoding="utf-8"
    )
    handler.setLevel(logging.DEBUG)
    handler.setFormatter(JSONFormatter())
    
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(JSONFormatter())
    
    logger.addHandler(handler)
    logger.addHandler(console_handler)
    
    return logger


def get_trace_id() -> Optional[str]:
    return trace_id_var.get()


def set_trace_id(trace_id: str) -> None:
    trace_id_var.set(trace_id)


def clear_trace_id() -> None:
    trace_id_var.set(None)


class TraceContext:
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or generate_trace_id()
        self.token = None
    
    def __enter__(self):
        self.token = trace_id_var.set(self.trace_id)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            trace_id_var.reset(self.token)
        return False
