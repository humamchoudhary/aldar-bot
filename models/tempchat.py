from datetime import datetime


class TempMessage:
    def __init__(self, sender, content):
        self.sender = sender
        self.content = content
        self.timestamp = datetime.utcnow()

    def to_dict(self):
        return {
            'sender': self.sender,
            'content': self.content,
            'timestamp': self.timestamp.isoformat()
        }

    @classmethod
    def from_dict(cls, data):
        message = cls(data['sender'], data['content'])
        if data.get('timestamp'):
            message.timestamp = datetime.fromisoformat(data['timestamp'])
        return message


class TempChat:
    def __init__(self, chat_id, room_id, user_id, messages=None, subject="General", bot_name="Bot"):
        self.chat_id = chat_id
        self.room_id = room_id
        self.user_id = user_id
        self.messages = messages or []
        self.subject = subject
        self.bot_name = bot_name
        self.admin_required = False
        self.admin_present = False
        self.open = True
        self.created_at = datetime.utcnow()
        self.updated_at = datetime.utcnow()

    @property
    def title(self):
        """Generate a title for the chat"""
        return self.subject if self.subject != "General" else f"Chat {self.chat_id[:8]}"

    def to_dict(self):
        return {
            'chat_id': self.chat_id,
            'room_id': self.room_id,
            'user_id': self.user_id,
            'messages': [msg.to_dict() for msg in self.messages],
            'subject': self.subject,
            'bot_name': self.bot_name,
            'admin_required': self.admin_required,
            'admin_present': self.admin_present,
            'open': self.open,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data):
        messages = [TempMessage.from_dict(msg_data) for msg_data in data.get('messages', [])]
        
        chat = cls(
            chat_id=data['chat_id'],
            room_id=data['room_id'],
            user_id=data['user_id'],
            messages=messages,
            subject=data.get('subject', 'General'),
            bot_name=data.get('bot_name', 'Bot')
        )
        
        chat.admin_required = data.get('admin_required', False)
        chat.admin_present = data.get('admin_present', False)
        chat.open = data.get('open', True)
        
        if data.get('created_at'):
            chat.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('updated_at'):
            chat.updated_at = datetime.fromisoformat(data['updated_at'])
            
        return chat

    def __str__(self):
        return f"TempChat(chat_id={self.chat_id}, subject={self.subject}, messages={len(self.messages)})"
