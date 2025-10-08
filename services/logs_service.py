from datetime import datetime
from typing import Optional, Dict, Any
from pymongo import MongoClient
from pymongo.collection import Collection
from models.log import LogEntry, LogLevel, LogTag


class LogsService:
    def __init__(self, db: MongoClient):
        self.db = db
        self.logs_collection: Collection = db.logs

    def create_log(
        self,
        level: LogLevel,
        tag: LogTag,
        message: str,
        user_id: Optional[str] = None,
        admin_id: Optional[str] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> LogEntry:
        """Create and store a new log entry"""
        log_entry = LogEntry(
            level=level,
            tag=tag,
            message=message,
            user_id=user_id,
            admin_id=admin_id,
            data=data
        )
        self.logs_collection.insert_one(log_entry.to_dict())
        return log_entry

    def get_log_by_id(self, log_id: str) -> Optional[LogEntry]:
        """Retrieve a log entry by its ID"""
        log_data = self.logs_collection.find_one({"log_id": log_id})
        return LogEntry.from_dict(log_data) if log_data else None

    def get_logs_by_user(self, user_id: str, limit: int) -> list[LogEntry]:
        """Get all logs for a specific user"""
        logs = self.logs_collection.find(
            {"user_id": user_id}
        ).sort("timestamp", -1)

        if limit:
            logs = logs.limit(int(limit))
        return [LogEntry.from_dict(log) for log in logs]

    def get_logs_by_admin(self, admin_id: str, limit: int) -> list[LogEntry]:
        """Get all logs created by a specific admin"""
        logs = self.logs_collection.find(
            {"admin_id": admin_id}
        ).sort("timestamp", -1)
        if limit:
            logs = logs.limit(int(limit))

        return [LogEntry.from_dict(log) for log in logs]

    def get_logs_by_tag(self, tag: LogTag, limit: int) -> list[LogEntry]:
        """Get all logs with a specific tag"""
        logs = self.logs_collection.find(
            {"tag": tag.value}
        ).sort("timestamp", -1)

        if limit:
            logs = logs.limit(int(limit))
        return [LogEntry.from_dict(log) for log in logs]

    def get_recent_logs(self, admin_id: Optional[str] = None, limit: int = 100) -> list[LogEntry]:
        """Get most recent logs with optional admin_id filter"""
        query = {}
        if admin_id is not None:
            query['admin_id'] = admin_id

        logs = self.logs_collection.find(query).sort("timestamp", -1)
        if limit:
            logs = logs.limit(int(limit))
        return [LogEntry.from_dict(log) for log in logs]

    def search_logs(
        self,
        level: Optional[LogLevel] = None,
        tag: Optional[LogTag] = None,
        user_id: Optional[str] = None,
        admin_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = None,
    ) -> list[LogEntry]:
        """Advanced log search with multiple filters"""
        query = {}

        if level:
            query["level"] = level.value
        if tag:
            query["tag"] = tag.value
        if user_id:
            query["user_id"] = user_id
        if admin_id:
            query["admin_id"] = admin_id
        if start_date or end_date:
            query["timestamp"] = {}
            if start_date:
                query["timestamp"]["$gte"] = start_date
            if end_date:
                query["timestamp"]["$lte"] = end_date

        logs = self.logs_collection.find(
            query).sort("timestamp", -1)

        if limit:
            logs = logs.limit(int(limit))
        return [LogEntry.from_dict(log) for log in logs]

    def search_logs_advanced(self, levels=None, tags=None, user_id=None, admin_id=None,
                             message_search=None, start_date=None, end_date=None, limit=None,
                             current_admin_id: Optional[str] = None):
        """
        Advanced search with admin restrictions
        """
        query = {}

        # Apply admin restriction if current_admin_id is provided
        if current_admin_id is not None:
            query['admin_id'] = current_admin_id

        # Multiple level filtering
        if levels:
            level_values = [level.value for level in levels]
            query['level'] = {'$in': level_values}

        # Multiple tag filtering
        if tags:
            tag_values = [tag.value for tag in tags]
            query['tag'] = {'$in': tag_values}

        # User ID filtering
        if user_id:
            query['user_id'] = user_id

        # Specific admin filtering (only for superadmin)
        if admin_id and current_admin_id is None:
            query['admin_id'] = admin_id

        # Message content search
        if message_search:
            query['message'] = {'$regex': message_search, '$options': 'i'}

        # Date range filtering
        if start_date or end_date:
            date_query = {}
            if start_date:
                date_query['$gte'] = start_date
            if end_date:
                date_query['$lte'] = end_date
            query['timestamp'] = date_query

        cursor = self.logs_collection.find(query).sort('timestamp', -1)
        if limit:
            cursor = cursor.limit(int(limit))

        return [LogEntry.from_dict(log) for log in cursor]
        # for doc in cursor:
        #     try:
        #         log = LogEntry(
        #             level=LogLevel(doc['level']),
        #             tag=LogTag(doc['tag']),
        #             message=doc['message'],
        #             timestamp=doc['timestamp'],
        #             user_id=doc.get('user_id'),
        #             admin_id=doc.get('admin_id'),
        #             data=doc.get('data', {})
        #         )
        #         logs.append(log)
        #     except (ValueError, KeyError) as e:
        #         # Skip invalid logs
        #         continue
        #
        # return logs
