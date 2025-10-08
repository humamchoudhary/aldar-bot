"""
LOGS TEMPLATE:
    Level: [DEBUG, INFO, WARNING, ERROR, CRITICAL]
    Tag: ['ACCESS','Message','PING','LOGIN','LOGOUT']
    User: User ID | Admin ID
    MSG: Message
    Data: Request Headers
    Time: DD:MM:YYYY - hh:mm:ss

"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

    def __str__(self):
        return str(self.value)

class LogTag(Enum):
    ACCESS = "ACCESS"
    MESSAGE = "MESSAGE"
    PING = "PING"
    LOGIN = "LOGIN"
    LOGOUT = "LOGOUT"
    ADMIN = "ADMIN"
    SYSTEM = "SYSTEM"

    def __str__(self):
        return str(self.value)


class LogEntry:
    def __init__(
        self,
        level: LogLevel,
        tag: LogTag,
        message: str,
        user_id: Optional[str] = None,
        admin_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None,
        timestamp: Optional[datetime] = None,
    ):
        self.log_id = str(uuid.uuid4())
        self.level = level
        self.tag = tag
        self.user_id = user_id
        self.admin_id = admin_id
        self.message = message
        self.data = data or {}
        self.timestamp = timestamp or datetime.utcnow()

        # if not user_id and not admin_id:
        #     raise ValueError("Either user_id or admin_id must be provided")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "log_id": self.log_id,
            "level": self.level.value,
            "tag": self.tag.value,
            "user_id": self.user_id,
            "admin_id": self.admin_id,
            "message": self.message,
            "data": self.data,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'LogEntry':
        log = cls(
            level=LogLevel(data["level"]),
            tag=LogTag(data["tag"]),
            message=data["message"],
            user_id=data.get("user_id"),
            admin_id=data.get("admin_id"),
            data=data.get("data", {}),
            timestamp=data["timestamp"]
        )
        log.log_id = data['log_id']
        return log
