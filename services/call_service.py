import uuid
import os
from datetime import datetime
from typing import TypedDict, Literal, Optional
from pymongo.collection import Collection

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
    userdata: dict

class CallService:
    def __init__(self, db):
        self.db = db
        self.call_collection: Collection[Call] = db.calls
    
    def create_call(self, call_id, data):
        """Create a new call record."""
        self.call_collection.insert_one(
            Call(
                call_id=call_id,
                status="ongoing",
                started_at=data.get("started_at", datetime.now()),
                ended_at=None,
                audio=data.get("file_name", f"call_{call_id}.wav"),
                transcription=[],userdata=data.get("custom_params",{"name":"","qid":0})
            )
        )
    
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
                    "ended_at": datetime.now()
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
            'call_id': 1,
            'status': 1,
            'started_at': 1,
            'ended_at': 1,
            'audio': 1,
            # Exclude heavy transcription field
            # 'transcription': 0
        }
        
        calls = list(
            self.call_collection.find(query, projection)
            .sort("started_at", -1)
            .skip(skip)
            .limit(limit)
        )
        
        # Rename started_at to call_time for template compatibility
        for call in calls:
            call['call_time'] = call.pop('started_at')
        
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
        call = self.call_collection.find_one({"call_id": call_id})
        if call:
            # Rename for template compatibility
            if 'started_at' in call:
                call['call_time'] = call.pop('started_at')
        return call
    
    def delete_call(self, call_id):
        """Delete a call record."""
        result = self.call_collection.delete_one({"call_id": call_id})
        return result.deleted_count > 0
