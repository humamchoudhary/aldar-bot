import uuid
import os
from datetime import datetime, timezone
from typing import TypedDict, Literal, Optional
from pymongo.collection import Collection
from bson import ObjectId

class WhatsappUser(TypedDict):
    phone_no: str
    messages: list
    updated_at: datetime
    created_at: datetime
    admin_enabled:bool

class WhatsappService:
    def __init__(self, db):
        self.db = db
        self.whatsapp_collection: Collection[WhatsappUser] = db.whatsapp
    
    def create(self, phone_no):
        wa_doc = {
            "phone_no": phone_no,
            "messages": [],
            "created_at": datetime.now(timezone.utc),
            "updated_at": datetime.now(timezone.utc),
            "admin_enabled":False
        }
        self.whatsapp_collection.insert_one(wa_doc)

    def toggle_enabled_admin(self,phone_no):
        return self.whatsapp_collection.update_one(
    {"phone_no": phone_no},
    [
        {"$set": {"admin_enable": {"$not": "$admin_enable"}}}
    ]
)
    
    def add_message(self, message, phone_no: str, sender, type="text", audio_bytes=None):
        """
        Add a message to the database and save audio file if provided
        
        Args:
            message: The text message or transcription
            phone_no: Phone number of the user
            sender: Sender identifier (phone_no or "bot")
            type: Message type ("text" or "audio")
            audio_bytes: Audio file bytes (only for audio messages)
        
        Returns:
            Message object with id if successful, None otherwise
        """
        chat = self.get_by_phone_no(phone_no)
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
            # Determine file extension based on sender
            file_extension = ".wav" if sender == "bot" else ".ogg"
            file_path = os.path.join('files', phone_no, f"{message_id}{file_extension}")
            
            # Create directory if it doesn't exist
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            # Save audio file
            with open(file_path, 'wb') as f:
                f.write(audio_bytes)
            
            print(f"Saved audio file: {file_path}")
            message_doc["audio_path"] = file_path
        
        print({"phone_no": phone_no})
        
        # Update database
        result = self.whatsapp_collection.update_one(
            {"phone_no": phone_no},
            {
                "$push": {"messages": message_doc},
                "$set": {"updated_at": datetime.now(timezone.utc)}
            }
        )
        
        return message_id
            # return type('Message', (), message_doc)()  # Return message object
        # return None
    
    def get_by_phone_no(self, phone_no):
        chat_data = self.whatsapp_collection.find_one(
            {"phone_no": phone_no},
            {"_id": 0}
        )
        return chat_data
    
    def get_messages(self, phone_no, limit=50):
        """Get recent messages for a phone number"""
        chat = self.get_by_phone_no(phone_no)
        if not chat:
            return []
        
        messages = chat.get("messages", [])
        return messages[-limit:] if len(messages) > limit else messages
    
    def get_message_by_id(self, phone_no, message_id):
        """Get a specific message by ID"""
        chat = self.get_by_phone_no(phone_no)
        if not chat:
            return None
        
        for msg in chat.get("messages", []):
            if msg.get("id") == message_id:
                return msg
        return None

    def get_all_chats(self):
        chat_data = self.whatsapp_collection.find(
            {},
            {"_id": 0}
        )
        return chat_data

