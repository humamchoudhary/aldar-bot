from datetime import datetime


class TempUser:
    def __init__(self, name, user_id, ip=None, role="user", city=None, country=None):
        self.name = name
        self.user_id = user_id
        self.ip = ip
        self.role = role
        self.city = city
        self.country = country
        self.created_at = datetime.utcnow()
        self.last_active = datetime.utcnow()

    def to_dict(self):
        return {
            'name': self.name,
            'user_id': self.user_id,
            'ip': self.ip,
            'role': self.role,
            'city': self.city,
            'country': self.country,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_active': self.last_active.isoformat() if self.last_active else None
        }

    @classmethod
    def from_dict(cls, data):
        user = cls(
            name=data['name'],
            user_id=data['user_id'],
            ip=data.get('ip'),
            role=data.get('role', 'user'),
            city=data.get('city'),
            country=data.get('country')
        )
        
        if data.get('created_at'):
            user.created_at = datetime.fromisoformat(data['created_at'])
        if data.get('last_active'):
            user.last_active = datetime.fromisoformat(data['last_active'])
            
        return user

    def __str__(self):
        return f"TempUser(name={self.name}, user_id={self.user_id}, role={self.role})"
