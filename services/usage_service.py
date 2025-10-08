from datetime import datetime, UTC
from pymongo import MongoClient
from typing import Dict, Any, List


class UsageService:
    def __init__(self, db):
        self.db = db
        self.collection = db.usage

    def get_cost(self, admin_id: str) -> Dict[str, Any]:
        """Retrieves all token usage data for a specific admin as a structured dictionary."""
        usage_data = {}
        for doc in self.collection.find({"admin_id": admin_id}):
            period = doc["period"]
            date = doc["date"]
            if period not in usage_data:
                usage_data[period] = {}
            usage_data[period][date] = {
                "cost": doc.get("cost", []),
                "input_tokens": doc.get("input_tokens", []),
                "output_tokens": doc.get("output_tokens", []),
            }
        return usage_data

    def add_cost(self, admin_id: str, input_tokens: int, output_tokens: int, cost: float):
        """Logs token usage for a specific admin into daily (hourly), monthly (daily), and yearly (monthly) records."""
        now = datetime.now(UTC)

        hour_index = now.hour
        day_index = now.day - 1  # 0-based index
        month_index = now.month - 1  # 0-based index for months

        periods = {
            "daily": (now.strftime("%Y-%m-%d"), 24, hour_index),
            # Max days in month
            "monthly": (now.strftime("%Y-%m"), 31, day_index),
            "yearly": (now.strftime("%Y"), 12, month_index),
        }

        for period, (date_key, size, index) in periods.items():
            query = {"admin_id": admin_id, "period": period, "date": date_key}

            # Ensure array exists and has the correct size
            existing_doc = self.collection.find_one(query)
            if not existing_doc:
                self.collection.insert_one({
                    "admin_id": admin_id,
                    "period": period,
                    "date": date_key,
                    "cost": [0] * size,
                    "input_tokens": [0] * size,
                    "output_tokens": [0] * size,
                    "last_updated": now
                })

            # Increment specific index
            self.collection.update_one(
                query,
                {
                    "$inc": {
                        f"cost.{index}": cost,
                        f"input_tokens.{index}": input_tokens,
                        f"output_tokens.{index}": output_tokens,
                    },
                    "$set": {"last_updated": now}
                },
            )

    def get_admin_usage_summary(self, admin_id: str) -> Dict[str, Any]:
        """Gets a summary of usage for a specific admin across all periods."""
        summary = {
            "daily": {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0},
            "monthly": {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0},
            "yearly": {"total_cost": 0, "total_input_tokens": 0, "total_output_tokens": 0},
        }

        for doc in self.collection.find({"admin_id": admin_id}):
            period = doc["period"]
            if period in summary:
                summary[period]["total_cost"] += sum(doc.get("cost", []))
                summary[period]["total_input_tokens"] += sum(
                    doc.get("input_tokens", []))
                summary[period]["total_output_tokens"] += sum(
                    doc.get("output_tokens", []))

        return summary

    def get_all_admins_usage(self) -> Dict[str, Dict[str, Any]]:
        """Retrieves usage data for all admins."""
        admins_usage = {}
        for doc in self.collection.find():
            admin_id = doc["admin_id"]
            if admin_id not in admins_usage:
                admins_usage[admin_id] = {}

            period = doc["period"]
            date = doc["date"]
            if period not in admins_usage[admin_id]:
                admins_usage[admin_id][period] = {}

            admins_usage[admin_id][period][date] = {
                "cost": doc.get("cost", []),
                "input_tokens": doc.get("input_tokens", []),
                "output_tokens": doc.get("output_tokens", []),
            }
        
        return admins_usage

    def delete_admin_usage(self, admin_id: str):
        """Deletes all usage data for a specific admin."""
        self.collection.delete_many({"admin_id": admin_id})


def log_usage(admin_id: str, input_tokens: int, output_tokens: int, cost: float):
    """Logs token usage for a specific admin."""
    now = datetime.now(UTC)

    hour_index = now.hour
    day_index = now.day - 1  # 0-based index
    month_index = now.month - 1  # 0-based index for months

    periods = {
        "daily": (now.strftime("%Y-%m-%d"), 24, hour_index),
        "monthly": (now.strftime("%Y-%m"), 31, day_index),
        "yearly": (now.strftime("%Y"), 12, month_index),
    }

    for period, (date_key, size, index) in periods.items():
        query = {"admin_id": admin_id, "period": period, "date": date_key}

        # Ensure array exists and has the correct size
        existing_doc = collection.find_one(query)
        if not existing_doc:
            collection.insert_one({
                "admin_id": admin_id,
                "period": period,
                "date": date_key,
                "cost": [0] * size,
                "input_tokens": [0] * size,
                "output_tokens": [0] * size,
                "last_updated": now
            })

        # Increment specific index
        collection.update_one(
            query,
            {
                "$inc": {
                    f"cost.{index}": cost,
                    f"input_tokens.{index}": input_tokens,
                    f"output_tokens.{index}": output_tokens,
                },
                "$set": {"last_updated": now}
            },
        )


def get_usage(admin_id: str) -> Dict[str, Any]:
    """Retrieves usage data for a specific admin."""
    usage_data = {}
    for doc in collection.find({"admin_id": admin_id}):
        period = doc["period"]
        date = doc["date"]
        if period not in usage_data:
            usage_data[period] = {}
        usage_data[period][date] = {
            "cost": doc.get("cost", []),
            "input_tokens": doc.get("input_tokens", []),
            "output_tokens": doc.get("output_tokens", []),
        }
    return usage_data


def get_all_admins_usage() -> Dict[str, Dict[str, Any]]:
    """Retrieves usage data for all admins."""
    admins_usage = {}
    for doc in collection.find():
        admin_id = doc["admin_id"]
        if admin_id not in admins_usage:
            admins_usage[admin_id] = {}
        
        period = doc["period"]
        date = doc["date"]
        if period not in admins_usage[admin_id]:
            admins_usage[admin_id][period] = {}
        
        admins_usage[admin_id][period][date] = {
            "cost": doc.get("cost", []),
            "input_tokens": doc.get("input_tokens", []),
            "output_tokens": doc.get("output_tokens", []),
        }
    
    return admins_usage


if __name__ == "__main__":
    client = MongoClient("mongodb://localhost:27017/")
    db = client["test"]
    collection = db["usage"]
    
    # Example usage
    usage_service = UsageService(db)
    
    # Log usage for different admins
    usage_service.add_cost("admin_123", 100, 10, 400)
    usage_service.add_cost("admin_456", 50, 5, 200)
    usage_service.add_cost("admin_123", 75, 8, 300)
    
    # Get usage for specific admin
    admin_123_usage = usage_service.get_cost("admin_123")
    print("Admin 123 usage:", admin_123_usage)
    
    # Get usage summary for admin
    admin_summary = usage_service.get_admin_usage_summary("admin_123")
    print("Admin 123 summary:", admin_summary)
    
    # Get usage for all admins
    all_usage = usage_service.get_all_admins_usage()
    print("All admins usage:", all_usage)
