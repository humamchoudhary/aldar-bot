import uuid
import bcrypt
import random
import string
from models.admin import Admin
from datetime import datetime, timedelta


class AdminService:
    def __init__(self, db):
        self.db = db
        self.admins_collection = db.admins
        self.two_fa_collection = db.two_fa_tokens
        self.trusted_ips_collection = db.trusted_ips

    def create_admin(self, username, password, role="admin", email=None, phone=None, created_by=None):
        """Create a new admin"""
        # Check if username already exists
        if self.get_admin_by_username(username):
            raise ValueError("Username already exists")

        admin_id = str(uuid.uuid4())
        password_hash = bcrypt.hashpw(password.encode(
            'utf-8'), bcrypt.gensalt()).decode('utf-8')

        admin = Admin(
            username=username,
            password_hash=password_hash,
            role=role,
            admin_id=admin_id,
            email=email,
            phone=phone,
            created_by=created_by,
            tokens=120,
        )
        admin.onboarding = False

        self.admins_collection.insert_one(admin.to_dict())
        return admin

    def toggle_two_fa(self, admin_id):
        admin = self.get_admin_by_id(admin_id)
        self.admins_collection.update_one(
            {'admin_id': admin_id}, {"$set": {'two_fa': not admin.two_fa}})

    def add_expo_token(self, admin_id, token):
        return self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$addToSet": {"expo_token": token}},  # avoids duplicates
            upsert=True
        )

    def get_expo_tokens(self, admin_id):
        admin = self.admins_collection.find_one(
            {"admin_id": admin_id},
            {"_id": 0, "expo_token": 1}  # only return expo_token field
        )
        # print(admin_id)
        if admin and "expo_token" in admin:
            return admin["expo_token"]
        return []

    def get_admin_by_key(self, key):
        admin_data = self.admins_collection.find_one({"secret_key": key})
        if admin_data:
            return Admin.from_dict(admin_data)
        return None

    def update_tokens(self, admin_id, cost):
        self.admins_collection.update_one(
            {'admin_id': admin_id},
            {"$inc": {"tokens": -cost}}
        )

    def get_admin_by_username(self, username):
        """Get admin by username"""
        admin_data = self.admins_collection.find_one({"username": username})
        if admin_data:
            return Admin.from_dict(admin_data)
        return None

    def get_admin_by_id(self, admin_id):
        """Get admin by ID"""
        admin_data = self.admins_collection.find_one({"admin_id": admin_id})
        if admin_data:
            return Admin.from_dict(admin_data)
        return None

    def authenticate_admin(self, username, password):
        """Authenticate admin credentials"""
        admin = self.get_admin_by_username(username)
        if admin and admin.status == "active":
            if bcrypt.checkpw(password.encode('utf-8'), admin.password_hash.encode('utf-8')):
                # Update last login
                self.update_last_login(admin.admin_id)
                return admin
        return None

    def get_admin_from_sec(self, secrect_key):
        return Admin.from_dict(self.admins_collection.find_one({'secret_key': secrect_key}))

    def get_all_admins(self):
        """Get all admins"""
        admins = self.admins_collection.find()
        return [Admin.from_dict(admin) for admin in admins]

    def get_admins_by_role(self, role):
        """Get admins by role"""
        admins = self.admins_collection.find({"role": role})
        return [Admin.from_dict(admin) for admin in admins]

    def update_admin_settings(self, admin_id, settings):
        """Update admin settings"""
        result = self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"settings": settings}}
        )
        return result.modified_count > 0


    def update_admin_password(self, admin_id, new_password):
        """Update admin password"""
        password_hash = bcrypt.hashpw(new_password.encode(
            'utf-8'), bcrypt.gensalt()).decode('utf-8')
        result = self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"password_hash": password_hash}}
        )
        return result.modified_count > 0

    def set_admin_onboarded(self, admin_id):
        result = self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"onboarding": False}}
        )
        return result.modified_count > 0

    def update_admin_login(self, admin_id, username, password, email, phone):
        self.update_admin_password(admin_id, password)
        result = self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"email": email, 'username': username,
                      'phone': phone, 'onboarding': False}}
        )
        return result.modified_count > 0

    def update_admin_status(self, admin_id, status):
        """Update admin status (active, inactive, suspended)"""
        result = self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"status": status}}
        )
        return result.modified_count > 0

    def update_admin_role(self, admin_id, role):
        """Update admin role"""
        result = self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"role": role}}
        )
        return result.modified_count > 0

    def update_last_login(self, admin_id):
        """Update last login timestamp"""
        self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {"last_login": datetime.utcnow()}}
        )

    def delete_admin(self, admin_id):
        """Delete admin (only superadmin can do this)"""
        result = self.admins_collection.delete_one({"admin_id": admin_id})
        return result.deleted_count > 0

    def count_admins_by_role(self):
        """Count admins by role"""
        pipeline = [
            {"$group": {"_id": "$role", "count": {"$sum": 1}}}
        ]
        result = list(self.admins_collection.aggregate(pipeline))
        counts = {"admin": 0, "superadmin": 0}
        for item in result:
            counts[item["_id"]] = item["count"]
        return counts

    def get_admin_activity(self, days=30):
        """Get admin login activity for the last N days"""
        from datetime import timedelta
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        pipeline = [
            {"$match": {"last_login": {"$gte": cutoff_date}}},
            {"$project": {
                "username": 1,
                "role": 1,
                "last_login": 1,
                "status": 1
            }},
            {"$sort": {"last_login": -1}}
        ]

        result = list(self.admins_collection.aggregate(pipeline))
        return result

    def create_password_reset_token(self, admin_id):
        """Create a password reset token that expires in 1 hour"""
        token = str(uuid.uuid4())
        expires_at = datetime.utcnow() + timedelta(hours=1)

        self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$set": {
                "password_reset_token": token,
                "password_reset_expires": expires_at
            }}
        )
        return token

    def validate_password_reset_token(self, token):
        """Validate a password reset token"""
        admin_data = self.admins_collection.find_one({
            "password_reset_token": token,
            "password_reset_expires": {"$gt": datetime.utcnow()}
        })
        if admin_data:
            return Admin.from_dict(admin_data)
        return None

    def clear_password_reset_token(self, admin_id):
        """Clear the password reset token"""
        self.admins_collection.update_one(
            {"admin_id": admin_id},
            {"$unset": {
                "password_reset_token": "",
                "password_reset_expires": ""
            }}
        )

    # ===== 2FA Methods =====

    def generate_2fa_code(self):
        """Generate a 6-digit 2FA code"""
        return ''.join(random.choices(string.digits, k=6))

    def can_request_2fa(self, admin_id, ip_address):
        """Check if IP can request new 2FA code (30-minute cooldown)"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=2)
        existing_token = self.two_fa_collection.find_one({
            "admin_id": admin_id,
            "ip_address": ip_address,
            "created_at": {"$gt": cutoff_time},
            "status": "active"
        })
        return existing_token is None

    def create_2fa_token(self, admin_id, ip_address, two_fa_settings):
        """Create a new 2FA token for the IP address"""
        # Clean up expired tokens first
        self.cleanup_expired_2fa_tokens(two_fa_settings)

        # Check if IP can request new 2FA
        if not self.can_request_2fa(admin_id, ip_address):
            return None

        # Deactivate any existing active tokens for this admin/IP combo
        self.two_fa_collection.update_many(
            {"admin_id": admin_id, "ip_address": ip_address, "status": "active"},
            {"$set": {"status": "superseded"}}
        )

        code = self.generate_2fa_code()
        code_hash = bcrypt.hashpw(code.encode(
            'utf-8'), bcrypt.gensalt()).decode('utf-8')
        token_id = str(uuid.uuid4())
        # 2FA code expires in 10 minutes
        expires_at = datetime.utcnow() + timedelta(minutes=10)

        token_data = {
            "token_id": token_id,
            "admin_id": admin_id,
            "ip_address": ip_address,
            "code_hash": code_hash,
            "created_at": datetime.utcnow(),
            "expires_at": expires_at,
            "status": "active",  # active, used, expired, superseded
            "attempts": 0,
            "max_attempts": 3
        }

        self.two_fa_collection.insert_one(token_data)
        return {
            "token_id": token_id,
            "code": code,  # Return plaintext code only for sending to user
            "expires_at": expires_at
        }

    def verify_2fa_code(self, admin_id, ip_address, code):
        """Verify 2FA code for specific admin and IP"""
        token_data = self.two_fa_collection.find_one({
            "admin_id": admin_id,
            "ip_address": ip_address,
            "status": "active",
            "expires_at": {"$gt": datetime.utcnow()}
        })

        if not token_data:
            return {"success": False, "error": "No valid 2FA token found"}

        # Check attempts limit
        if token_data["attempts"] >= token_data["max_attempts"]:
            self.two_fa_collection.update_one(
                {"token_id": token_data["token_id"]},
                {"$set": {"status": "expired"}}
            )
            return {"success": False, "error": "Maximum attempts exceeded"}

        # Increment attempts
        self.two_fa_collection.update_one(
            {"token_id": token_data["token_id"]},
            {"$inc": {"attempts": 1}}
        )

        # Verify code using bcrypt
        if bcrypt.checkpw(code.encode('utf-8'), token_data["code_hash"].encode('utf-8')):
            # Mark as used
            self.two_fa_collection.update_one(
                {"token_id": token_data["token_id"]},
                {"$set": {"status": "used", "used_at": datetime.utcnow()}}
            )
            return {"success": True, "token_id": token_data["token_id"]}
        else:
            remaining_attempts = token_data["max_attempts"] - \
                token_data["attempts"]
            return {
                "success": False,
                "error": f"Invalid code. {remaining_attempts} attempts remaining"
            }

    def get_2fa_cooldown_remaining(self, admin_id, ip_address):
        """Get remaining cooldown time in minutes"""
        cutoff_time = datetime.utcnow() - timedelta(minutes=2)
        token = self.two_fa_collection.find_one({
            "admin_id": admin_id,
            "ip_address": ip_address,
            "created_at": {"$gt": cutoff_time},
            "status": "active"
        }, sort=[("created_at", -1)])

        if token:
            elapsed = datetime.utcnow() - token["created_at"]
            remaining = timedelta(minutes=30) - elapsed
            return max(0, int(remaining.total_seconds() / 60))
        return 0

    def cleanup_expired_2fa_tokens(self, two_fa_settings):
        """Clean up expired 2FA tokens (older than 24 hours)"""

        cutoff_time = datetime.utcnow() - timedelta(**
                                                    {two_fa_settings["unit"]:
                                                     int(two_fa_settings["duration"])})
        self.two_fa_collection.delete_many({
            "created_at": {"$lt": cutoff_time}
        })

    def get_2fa_stats(self, admin_id, two_fa_settings):
        """Get 2FA usage statistics for an admin"""
        cutoff_time = datetime.utcnow() - timedelta(**
                                                    {two_fa_settings["unit"]:
                                                     int(two_fa_settings["duration"])})
        pipeline = [
            {"$match": {
                "admin_id": admin_id,
                "created_at": {"$gt": cutoff_time}
            }},
            {"$group": {
                "_id": "$status",
                "count": {"$sum": 1}
            }}
        ]
        result = list(self.two_fa_collection.aggregate(pipeline))
        stats = {"active": 0, "used": 0, "expired": 0, "superseded": 0}
        for item in result:
            stats[item["_id"]] = item["count"]
        return stats

    def is_ip_trusted(self, admin_id, ip_address, two_fa_settings):
        """Check if IP is trusted (has completed 2FA within last 30 mins)"""
        cutoff_time = datetime.utcnow() - timedelta(**
                                                    {two_fa_settings["unit"]:
                                                     int(two_fa_settings["duration"])})
        trusted_ip = self.trusted_ips_collection.find_one({
            "admin_id": admin_id,
            "ip_address": ip_address,
            "last_verified": {"$gt": cutoff_time}
        })
        return trusted_ip is not None

    def add_trusted_ip(self, admin_id, ip_address):
        """Add/update trusted IP with current timestamp"""
        self.trusted_ips_collection.update_one(
            {"admin_id": admin_id, "ip_address": ip_address},
            {"$set": {"last_verified": datetime.utcnow()}},
            upsert=True
        )

    def cleanup_expired_trusted_ips(self, two_fa_settings):
        """Clean up IPs older than 30 minutes"""
        cutoff_time = datetime.utcnow() - timedelta(**
                                                    {two_fa_settings["unit"]:
                                                     int(two_fa_settings["duration"])})
        self.trusted_ips_collection.delete_many({
            "last_verified": {"$lt": cutoff_time}
        })
