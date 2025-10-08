import uuid
from datetime import datetime, timedelta
from models.tempuser import TempUser
import requests


class TempUserService:
    # In-memory storage for temporary users
    _users = {}

    def __init__(self):
        pass

    def create_user(self, name, ip=None, role="user"):
        user_id = str(uuid.uuid4())

        # Get location info if IP is provided
        country = None
        city = None
        if ip:
            try:
                geo = requests.get(f"http://ip-api.com/json/{ip}", timeout=5)
                geo_data = geo.json()
                country = geo_data.get("country", None)
                city = geo_data.get("city")

                if not country:
                    geo = requests.get(f"https://ipwhois.app/json/{ip}", timeout=5)
                    geo_data = geo.json()
                    country = geo_data.get("country", None)
                    city = geo_data.get("city")
            except:
                # If geo lookup fails, continue without location data
                pass

        # print(f"City: {city}, Country: {country}")

        user = TempUser(
            name=name, user_id=user_id, ip=ip, role=role, city=city, country=country
        )

        # Store in memory
        self._users[user_id] = user
        return user

    def get_user_by_id(self, user_id):
        return self._users.get(user_id)

    def update_user(self, user):
        if user.user_id in self._users:
            self._users[user.user_id] = user
            return True
        return False

    def update_last_active(self, user_id):
        user = self.get_user_by_id(user_id)
        if user:
            user.last_active = datetime.utcnow()
            self.update_user(user)

    def delete_user(self, user_id):
        if user_id in self._users:
            del self._users[user_id]
            return True
        return False

    def get_all_users(self):
        return list(self._users.values())

    def cleanup_inactive_users(self, hours=24):
        """Remove users inactive for more than specified hours"""
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        inactive_users = [
            user_id
            for user_id, user in self._users.items()
            if user.last_active < cutoff_time
        ]

        for user_id in inactive_users:
            del self._users[user_id]

        return len(inactive_users)
