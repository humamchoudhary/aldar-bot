import uuid
from datetime import datetime, timedelta
from models.tempchat import TempChat, TempMessage


class TempChatService:
    # In-memory storage for temporary chats
    _chats = {}
    _user_chats = {}  # user_id -> [chat_ids]

    def __init__(self):
        pass

    def create_chat(self, user_id, subject):
        chat_id = str(uuid.uuid4())
        room_id = f"{user_id}-{chat_id[:8]}"

        # Add default bot message
        initial_messages = [
            TempMessage("bot", "How may I help you")
        ]

        chat = TempChat(
            chat_id=chat_id,
            room_id=room_id,
            user_id=user_id,
            messages=initial_messages,
            subject=subject
        )

        # Store chat
        self._chats[chat_id] = chat
        # Add to user's chat list
        if user_id not in self._user_chats:
            self._user_chats[user_id] = []
        self._user_chats[user_id].append(chat_id)
        return chat

    def get_chat_by_id(self, chat_id):
        return self._chats.get(chat_id)

    def get_chat_by_room_id(self, room_id):
        for chat in self._chats.values():
            if chat.room_id == room_id:
                return chat
        return None

    def get_user_chats(self, user_id):
        """Get all chats for a user"""
        chat_ids = self._user_chats.get(user_id, [])
        return [self._chats[chat_id] for chat_id in chat_ids if chat_id in self._chats]

    def add_message(self, chat_id, sender, content):
        chat = self.get_chat_by_id(chat_id)
        if not chat:
            return None

        message = TempMessage(sender, content)
        chat.messages.append(message)
        chat.updated_at = message.timestamp

        return message

    def set_admin_required(self, chat_id, required=True):
        chat = self.get_chat_by_id(chat_id)
        if chat:
            chat.admin_required = required

    def set_admin_present(self, chat_id, present=True):
        chat = self.get_chat_by_id(chat_id)
        if chat:
            chat.admin_present = present

    def close_chat(self, chat_id):
        chat = self.get_chat_by_id(chat_id)
        if chat:
            chat.open = False

    def delete_chat(self, chat_id):
        if chat_id in self._chats:
            chat = self._chats[chat_id]
            user_id = chat.user_id

            # Remove from user's chat list
            if user_id in self._user_chats:
                if chat_id in self._user_chats[user_id]:
                    self._user_chats[user_id].remove(chat_id)

            # Remove the chat
            del self._chats[chat_id]
            return True
        return False

    def delete_user_chats(self, user_id):
        """Delete all chats for a user"""
        chat_ids = self._user_chats.get(user_id, []).copy()
        for chat_id in chat_ids:
            self.delete_chat(chat_id)

        if user_id in self._user_chats:
            del self._user_chats[user_id]

    def get_all_chats(self, limit=100, skip=0):
        """Get all chats, sorted by updated_at"""
        all_chats = list(self._chats.values())
        all_chats.sort(key=lambda x: x.updated_at, reverse=True)
        return all_chats[skip:skip+limit]

    def cleanup_old_chats(self, minutes=10):
        """Remove chats older than specified minutes"""
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        to_delete = [chat_id for chat_id, chat in self._chats.items()
                     if chat.updated_at < cutoff]

        for chat_id in to_delete:
            del self._chats[chat_id]

        return len(to_delete)
