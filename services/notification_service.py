import uuid
from datetime import datetime, timedelta
from typing import List, Dict, Optional


class NotificationService:
    def __init__(self, db):
        self.db = db
        self.notifications_collection = db.notifications

    def create_notification(self, admin_id: str, title: str, message: str,
                            notification_type: str = "admin_required",
                            room_id: str = None, metadata: Dict = None) -> str:
        """Create a new notification"""
        notification_id = str(uuid.uuid4())

        notification = {
            "notification_id": notification_id,
            "admin_id": admin_id,
            "title": title,
            "message": message,
            "type": notification_type,
            "room_id": room_id,
            "metadata": metadata or {},
            "read": False,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }

        self.notifications_collection.insert_one(notification)
        return notification_id

    def get_notifications(self, admin_id: str, limit: int = 50,
                          unread_only: bool = False) -> List[Dict]:
        """Get notifications for an admin"""
        query = {"admin_id": admin_id}
        if unread_only:
            query["read"] = False

        notifications = self.notifications_collection.find(
                query,{"_id":0}).sort("created_at", -1).limit(limit)
        return list(notifications)

    def get_unread_count(self, admin_id: str) -> int:
        """Get count of unread notifications"""
        return self.notifications_collection.count_documents({
            "admin_id": admin_id,
            "read": False
        })

    def mark_notification_read(self, notification_id: str, admin_id: str) -> bool:
        """Mark a specific notification as read"""
        result = self.notifications_collection.update_one(
            {"notification_id": notification_id, "admin_id": admin_id},
            {"$set": {"read": True, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count > 0

    def mark_all_read(self, admin_id: str) -> int:
        """Mark all notifications as read for an admin"""
        result = self.notifications_collection.update_many(
            {"admin_id": admin_id, "read": False},
            {"$set": {"read": True, "updated_at": datetime.utcnow()}}
        )
        return result.modified_count

    def delete_notification(self, notification_id: str, admin_id: str) -> bool:
        """Delete a specific notification"""
        result = self.notifications_collection.delete_one({
            "notification_id": notification_id,
            "admin_id": admin_id
        })
        return result.deleted_count > 0

    def clear_all_notifications(self, admin_id: str) -> int:
        """Clear all notifications for an admin"""
        result = self.notifications_collection.delete_many(
            {"admin_id": admin_id})
        return result.deleted_count

    def get_notification_stats(self, admin_id: str, days: int = 30) -> Dict:
        """Get notification statistics"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {
                "admin_id": admin_id,
                "created_at": {"$gte": cutoff_date}
            }},
            {"$group": {
                "_id": "$type",
                "total": {"$sum": 1},
                "unread": {"$sum": {"$cond": [{"$eq": ["$read", False]}, 1, 0]}}
            }}
        ]

        result = list(self.notifications_collection.aggregate(pipeline))

        stats = {"total": 0, "unread": 0, "by_type": {}}
        for item in result:
            stats["total"] += item["total"]
            stats["unread"] += item["unread"]
            stats["by_type"][item["_id"]] = {
                "total": item["total"],
                "unread": item["unread"]
            }

        return stats

    def cleanup_old_notifications(self, days: int = 30) -> int:
        """Clean up notifications older than specified days"""
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        result = self.notifications_collection.delete_many({
            "created_at": {"$lt": cutoff_date}
        })
        return result.deleted_count

    def get_pending_admin_required_notifications(self, admin_id: str) -> List[Dict]:
        """Get pending admin_required notifications"""
        notifications = self.notifications_collection.find({
            "admin_id": admin_id,
            "type": "admin_required",
            "read": False
        }).sort("created_at", -1)

        return list(notifications)

    def create_admin_required_notification(self, admin_id: str, room_id: str,
                                           username: str = None) -> str:
        """Create admin required notification"""
        title = "Admin Required"
        message = f"A Chat room requires admin attention"
        if username:
            message = f"User {username} requires admin attention"

        return self.create_notification(
            admin_id=admin_id,
            title=title,
            message=message,
            notification_type="admin_required",
            room_id=room_id,
            metadata={"username": username} if username else None
        )

    def remove_admin_required_notification(self, admin_id: str, room_id: str) -> int:
        """Remove admin required notifications for a specific room"""
        result = self.notifications_collection.delete_many({
            "admin_id": admin_id,
            "type": "admin_required",
            "room_id": room_id
        })
        return result.deleted_count

    def get_notifications_for_room(self, admin_id: str, room_id: str) -> List[Dict]:
        """Get all notifications for a specific room"""
        notifications = self.notifications_collection.find({
            "admin_id": admin_id,
            "room_id": room_id
        }).sort("created_at", -1)

        return list(notifications)
