import uuid
import os
from datetime import datetime, timezone
from typing import TypedDict, Literal, Optional
from pymongo.collection import Collection

class FacebookUser(TypedDict):
    sender_id: str
    messages: list
    updated_at: datetime
    created_at: datetime
    admin_enabled: bool
    user_info: Optional[dict]  # Store user profile info like name, profile pic

class FacebookService:
    def __init__(self, db):
        self.db = db
        self.facebook_collection: Collection[FacebookUser] = db.facebook
    
    def create(self, sender_id, user_info=None):
        """Create a new Facebook user chat"""
        fb_doc = {
            "sender_id": sender_id,
            "messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "admin_enabled": False,
            "user_info": user_info or {}
        }
        self.facebook_collection.insert_one(fb_doc)
        return fb_doc

    def toggle_enabled_admin(self, sender_id):
        """Toggle admin enabled status for a user"""
        return self.facebook_collection.update_one(
            {"sender_id": sender_id},
            [
                {"$set": {"admin_enabled": {"$not": "$admin_enabled"}}}
            ]
        )
    
    def update_user_info(self, sender_id, user_info):
        """Update user profile information"""
        return self.facebook_collection.update_one(
            {"sender_id": sender_id},
            {
                "$set": {
                    "user_info": user_info,
                    "updated_at": datetime.now(timezone.utc)
                }
            }
        )
    
    def add_message(self, message, sender_id: str, sender, type="text", audio_bytes=None):
        """
        Add a message to the database and save audio file if provided
        
        Args:
            message: The text message or transcription
            sender_id: Facebook sender ID
            sender: Sender identifier (sender_id or "bot")
            type: Message type ("text" or "audio")
            audio_bytes: Audio file bytes (only for audio messages)
        
        Returns:
            Message ID if successful, None otherwise
        """
        chat = self.get_by_sender_id(sender_id)
        if not chat:
            return None
        
        # Generate unique message ID
        message_id = str(uuid.uuid4())
        
        # Create message document
        message_doc = {
            "id": message_id,
            "message": message,
            "sender": sender,
            "time": datetime.now(timezone.utc),
            "type": type
        }
        
        # Save audio file if provided
        if type == "audio" and audio_bytes:
            # Use MP3 for both user and bot messages on Messenger
            file_extension = ".mp3"
            file_path = os.path.join('files', 'facebook', sender_id, f"{message_id}{file_extension}")
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Save audio file
            with open(file_path, 'wb') as f:
                f.write(audio_bytes)
            
            print(f"Saved audio file: {file_path}")
            message_doc["audio_path"] = file_path
        
        # Update database
        result = self.facebook_collection.update_one(
            {"sender_id": sender_id},
            {
                "$push": {"messages": message_doc},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )
        
        return message_id
    
    def get_by_sender_id(self, sender_id):
        """Get chat by Facebook sender ID"""
        chat_data = self.facebook_collection.find_one(
            {"sender_id": sender_id},
            {"_id": 0}
        )
        return chat_data
    
    def get_messages(self, sender_id, limit=50):
        """Get recent messages for a sender ID"""
        chat = self.get_by_sender_id(sender_id)
        if not chat:
            return []
        
        messages = chat.get("messages", [])
        return messages[-limit:] if len(messages) > limit else messages
    
    def get_message_by_id(self, sender_id, message_id):
        """Get a specific message by ID"""
        chat = self.get_by_sender_id(sender_id)
        if not chat:
            return None
        
        for msg in chat.get("messages", []):
            if msg.get("id") == message_id:
                return msg
        return None

    def get_all_chats(self):
        """Get all Facebook chats"""
        chat_data = self.facebook_collection.find(
            {},
            {"_id": 0}
        )
        return list(chat_data)
    
    def delete_chat(self, sender_id):
        """Delete a chat and its messages"""
        result = self.facebook_collection.delete_one({"sender_id": sender_id})
        
        # Optionally delete audio files
        chat_dir = os.path.join('files', 'facebook', sender_id)
        if os.path.exists(chat_dir):
            import shutil
            shutil.rmtree(chat_dir)
        
        return result.deleted_count > 0
    
    def get_chat_statistics(self):
        """Get statistics about Facebook chats"""
        pipeline = [
            {
                "$project": {
                    "sender_id": 1,
                    "message_count": {"$size": "$messages"},
                    "created_at": 1,
                    "updated_at": 1,
                    "admin_enabled": 1
                }
            }
        ]
        return list(self.facebook_collection.aggregate(pipeline))
