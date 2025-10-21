import uuid
import os
from datetime import datetime
from typing import TypedDict, Literal, Optional
from pymongo.collection import Collection
from bson import ObjectId

class CallTranscription(TypedDict):
    speaker: str
    transcription: str

class Call(TypedDict):
    call_id: str
    status: Literal["ongoing", "ended", "in_progress"]
    started_at: datetime
    ended_at: Optional[datetime]
    audio: str
    transcription: list[CallTranscription]
    userdata: dict # {"From":"","name":"" or None, "qid":""or None}

class CallService:
    def __init__(self, db):
        self.db = db
        self.call_collection: Collection[Call] = db.calls
    
    def create_call(self, call_id, data):
        """Create a new call record."""
        # Ensure datetime objects are used
        started_at = data.get("started_at")
        if isinstance(started_at, str):
            started_at = datetime.fromisoformat(started_at.replace('Z', '+00:00'))
        elif started_at is None:
            started_at = datetime.utcnow()
        
        call_doc = {
            "call_id": call_id,
            "status": "ongoing",
            "started_at": started_at,  # Store as datetime
            "ended_at": None,
            "audio": data.get("file_name", f"call_{call_id}.wav"),
            "transcription": [],
            "userdata": data.get("custom_parameters", {"From": "", "name": None, "qid": None})
        }
        
        self.call_collection.insert_one(call_doc)
    
    def add_chunk(self, call_id, data):
        """Add transcription chunks to a call."""
        transcriptions: list[CallTranscription] = []
        for entry in data:
            transcriptions.append(
                CallTranscription(
                    speaker=entry["speaker"],
                    transcription=entry["transcription"]
                )
            )
        self.call_collection.update_one(
            {"call_id": call_id},
            {"$push": {"transcription": {"$each": transcriptions}}}
        )
    
    def end_call(self, call_id):
        """End a call."""
        self.call_collection.update_one(
            {"call_id": call_id},
            {
                "$set": {
                    "status": "ended",
                    "ended_at": datetime.utcnow()  # Store as datetime
                }
            }
        )
    
    def get_calls_with_limited_data(self, admin_id=None, limit=20, skip=0, filter_type='all'):
        """
        Get calls with only the data needed for list display.
        Excludes heavy transcription field.
        """
        query = {}
        
        # Apply filters
        if filter_type == 'ongoing':
            query['status'] = 'ongoing'
        elif filter_type == 'ended':
            query['status'] = 'ended'
        elif filter_type == 'in_progress':
            query['status'] = 'in_progress'
        
        # Projection - only fetch fields needed for list view
        projection = {
            # 'call_id': 1,
            # 'status': 1,
            # 'started_at': 1,
            # 'ended_at': 1,
            # 'audio': 1,
            # 'userdata': 1,
            # Exclude heavy transcription field
            'transcription': 0,
            '_id': 0  # Exclude MongoDB's _id field
        }
        
        calls = list(
            self.call_collection.find(query, projection)
            .sort("started_at", -1)
            .skip(skip)
            .limit(limit)
        )
        
        # MongoDB returns datetime objects by default - no conversion needed!
        # Just verify they are datetime objects
        for call in calls:
            # Convert started_at to datetime if it's a string
            if isinstance(call['started_at'], str):
                call['started_at'] = datetime.fromisoformat(call['started_at'].replace('Z', '+00:00'))
            
            # Convert ended_at to datetime if it exists and is a string
            if call.get('ended_at') and isinstance(call['ended_at'], str):
                call['ended_at'] = datetime.fromisoformat(call['ended_at'].replace('Z', '+00:00'))
        
        
        return calls
    
    def get_call_counts_by_filter(self, admin_id=None):
        """Get counts for all call filters."""
        base_query = {}
        
        return {
            'all': self.call_collection.count_documents(base_query),
            'ongoing': self.call_collection.count_documents({**base_query, 'status': 'ongoing'}),
            'ended': self.call_collection.count_documents({**base_query, 'status': 'ended'}),
            'in_progress': self.call_collection.count_documents({**base_query, 'status': 'in_progress'}),
        }
    
    def get_full_call(self, call_id):
        """Get complete call data including transcription for detail view."""
        call = self.call_collection.find_one({"call_id": call_id}, {"_id": 0})
        
        # MongoDB returns datetime objects natively - no conversion needed
        # Verify they are datetime objects
        if call:
            if isinstance(call['started_at'], str):
                call['started_at'] = datetime.fromisoformat(call['started_at'].replace('Z', '+00:00'))
            
            # Convert ended_at to datetime if it exists and is a string
            if call.get('ended_at') and isinstance(call['ended_at'], str):
                call['ended_at'] = datetime.fromisoformat(call['ended_at'].replace('Z', '+00:00'))
        
        return call
    
    def delete_call(self, call_id):
        """Delete a call record."""
        result = self.call_collection.delete_one({"call_id": call_id})
        return result.deleted_count > 0
