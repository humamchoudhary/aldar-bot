from datetime import datetime
from pprint import pprint


class Message:
    def __init__(self, sender, content, timestamp=None):
        self.sender = sender
        self.content = content
        self.timestamp = timestamp or datetime.utcnow()

    def to_dict(self):
        return {
            "sender": self.sender,
            "content": self.content,
            "timestamp": self.timestamp
        }

    @classmethod
    def from_dict(cls, data):
        return cls(
            sender=data.get("sender"),
            content=data.get("content"),
            timestamp=data.get("timestamp")
        )

    def __str__(self):
        return f"{self.to_dict()}"


class Chat:
    def __init__(self, chat_id, user_id, bot_name="bot", messages=None,
                 admin_required=False, admin_present=False, open=True, subject=None, exported=False, admin_id=None, lead_id=None, viewed=False, archived=False):
        self.chat_id = chat_id
        # Generate room_id from user_id and first 8 chars of chat_id
        self.room_id = f"{user_id}-{chat_id[:8]}"
        self.user_id = user_id
        self.bot_name = bot_name
        self.messages = messages or []
        self.admin_required = admin_required
        self.admin_present = admin_present
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()
        self.open = open
        self.subject = subject
        self.exported = exported
        self.admin_id = admin_id
        self.lead_id = lead_id
        self.viewed = viewed
        self.archived = archived

    def add_message(self, sender, content):
        message = Message(sender, content)
        self.messages.append(message)
        self.updated_at = datetime.utcnow()
        return message

    def to_dict(self):
        return {
            "chat_id": self.chat_id,
            "room_id": self.room_id,
            "user_id": self.user_id,
            "bot_name": self.bot_name,
            "messages": [m.to_dict() for m in self.messages],
            "admin_required": self.admin_required,
            "admin_present": self.admin_present,
            "subject": self.subject,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "exported": self.exported,
            "admin_id": self.admin_id,
            'lead_id': self.lead_id,
            'viewed': self.viewed,
            'archived': self.archived
        }

    @classmethod
    def from_dict(cls, data):
        messages = [Message.from_dict(m) for m in data.get("messages", [])]
        chat = cls(
            chat_id=data.get('chat_id'),
            user_id=data.get("user_id"),
            bot_name=data.get("bot_name", "ChatBot"),
            messages=messages,
            subject=data.get('subject'),
            admin_required=data.get("admin_required", False),
            admin_present=data.get("admin_present", False),
            exported=data.get('exported', False),
            admin_id=data.get('admin_id', None),
            lead_id=data.get("lead_id", None),
            viewed=data.get('viewed', False),
            archived=data.get('archived', False)
        )
        # Make sure to load the room_id from the data
        chat.room_id = data.get("room_id")
        chat.created_at = data.get("created_at", datetime.utcnow())
        chat.updated_at = data.get("updated_at")
        if not chat.updated_at:
            chat.updated_at = chat.created_at
        return chat
