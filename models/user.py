from datetime import datetime
import requests
import re


def extract_custom_domain_emails(text: str):
    """
    Extract emails with custom domains, filtering out common providers
    and their variations/typos.
    """

    # Common email providers and their variations/typos
    blocked_domains = {
        # Gmail variations
        'gmail.com', 'gmial.com', 'gmai.com', 'gmall.com', 'gmaill.com',
        'gmail.co', 'gmeil.com', 'gmal.com', 'gmaiil.com', 'gmil.com',

        # Yahoo variations
        'yahoo.com', 'yahoo.co.uk', 'yahoo.co.in', 'yaho.com', 'yahooo.com',
        'yahoo.ca', 'yahoo.fr', 'yahoo.de', 'yahho.com', 'ymail.com',

        # Outlook/Hotmail variations
        'outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'outlook.co.uk',
        'hotmail.co.uk', 'hotmial.com', 'outlok.com', 'hotmall.com',

        # Other common providers
        'aol.com', 'icloud.com', 'me.com', 'mac.com', 'protonmail.com',
        'mail.com', 'zoho.com', 'tutanota.com', 'fastmail.com',
        'rediffmail.com', 'qq.com', '163.com', '126.com',

        # Regional providers
        'mail.ru', 'yandex.ru', 'yandex.com', 'rambler.ru',
        'web.de', 'gmx.de', 'gmx.com', 't-online.de',
        'naver.com', 'daum.net', 'hanmail.net',
    }

    # Email regex pattern
    email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'

    # Find all emails
    emails = re.findall(email_pattern, text)

    # Filter out blocked domains
    custom_emails = []
    for email in emails:
        domain = email.split('@')[1].lower()
        if domain not in blocked_domains:
            custom_emails.append(email)

    # Remove duplicates while preserving order
    seen = set()
    unique_emails = []
    for email in custom_emails:
        if email.lower() not in seen:
            seen.add(email.lower())
            unique_emails.append(email)

    return unique_emails


class User:
    def __init__(
        self,
        name,
        ip=None,
        phone=None,
        email=None,
        user_id=None,
        country=None,
        city=None,
        role="user",
        chat_ids=None,
        desg=None,
        loc=None,
        db=None, company=None
    ):
        self.user_id = user_id
        self.name = name
        self.role = role
        self.chat_ids = chat_ids or []
        self.created_at = datetime.utcnow()
        self.last_active = datetime.utcnow()
        self.email = email
        self.phone = phone
        self.ip = ip
        # self.loc = loc
        self.country = country
        self.city = city
        self.desg = desg
        self.loc = loc
        self.company = company

        if ip.split(".")[0] not in ["192", "127"] and (city == None or country == None):

            geo = requests.get(f"http://ip-api.com/json/{ip}")
            # print(geo)
            geo = geo.json()
            # print(geo)
            self.country = geo.get("country", None)
            self.city = geo.get("city")
            if geo["status"] != "fail" and db != None:
                x = db.update_one(
                    {"user_id": user_id}, {
                        "$set": {"city": city, "country": country}}
                )
                # print(x)
        # if not self.company:
        #
        #     blocked_domains = {
        #         # Gmail variations
        #         'gmail.com', 'gmial.com', 'gmai.com', 'gmall.com', 'gmaill.com',
        #         'gmail.co', 'gmeil.com', 'gmal.com', 'gmaiil.com', 'gmil.com',
        #
        #         # Yahoo variations
        #         'yahoo.com', 'yahoo.co.uk', 'yahoo.co.in', 'yaho.com', 'yahooo.com',
        #         'yahoo.ca', 'yahoo.fr', 'yahoo.de', 'yahho.com', 'ymail.com',
        #
        #         # Outlook/Hotmail variations
        #         'outlook.com', 'hotmail.com', 'live.com', 'msn.com', 'outlook.co.uk',
        #         'hotmail.co.uk', 'hotmial.com', 'outlok.com', 'hotmall.com',
        #
        #         # Other common providers
        #         'aol.com', 'icloud.com', 'me.com', 'mac.com', 'protonmail.com',
        #         'mail.com', 'zoho.com', 'tutanota.com', 'fastmail.com',
        #         'rediffmail.com', 'qq.com', '163.com', '126.com',
        #
        #         # Regional providers
        #         'mail.ru', 'yandex.ru', 'yandex.com', 'rambler.ru',
        #         'web.de', 'gmx.de', 'gmx.com', 't-online.de',
        #         'naver.com', 'daum.net', 'hanmail.net',
        #     }
        #     if self.email.split("@")[-1] not in blocked_domains:
        #         self.company = self.email.split('@')[-1]
        #     else:
        self.company = self.name

    def to_dict(self):
        if self.loc and not (self.city and self.country):
            self.city, self.country = self.loc.split(",")

        return {
            "user_id": self.user_id,
            "name": self.name,
            "role": self.role,
            "chat_ids": self.chat_ids,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "email": self.email,
            "phone": self.phone,
            "ip": self.ip,
            "city": self.city,
            "country": self.country,
            "desg": self.desg,
            "loc": self.loc, 'company': self.company
        }

    @classmethod
    def from_dict(cls, data):
        user = cls(
            name=data.get("name"),
            user_id=data.get("user_id"),
            role=data.get("role", "user"),
            chat_ids=data.get("chat_ids", []),
            ip=data.get("ip"),
            city=data.get("city"),
            country=data.get("country"),
            email=data.get("email"),
            phone=data.get("phone"),
            desg=data.get("desg"),
            loc=data.get("loc"),
            db=data.get("db", None), company=data.get('company', None)
        )
        user.created_at = data.get("created_at", datetime.utcnow())
        user.last_active = data.get("last_active", datetime.utcnow())
        return user
