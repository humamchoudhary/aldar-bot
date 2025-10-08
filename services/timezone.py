from datetime import datetime, timedelta, timezone


class UTCZoneManager:
    def __init__(self):
        # Create a dictionary of timezones from UTC-12 to UTC+12
        self.timezones = {
            f"GMT{offset:+}": timezone(timedelta(hours=offset))
            for offset in range(-12, 13)  # -12 to +12 inclusive
        }

    @classmethod
    def get_timezones(cls):
        """Returns a list of supported timezones."""
        return list(
            {
                f"GMT{offset:+}": timezone(timedelta(hours=offset))
                for offset in range(-12, 13)  # -12 to +12 inclusive
            }.keys()
        )

    def get_current_date(self, tz_str: str) -> str:
        """
        Returns current date (YYYY-MM-DD) in the given timezone.

        Args:
            tz_str: A string like 'UTC+4', 'UTC-7', etc.

        Returns:
            A date string in the format 'YYYY-MM-DD'.
        """
        tz = self.timezones.get(tz_str)
        if not tz:
            raise ValueError(
                f"Invalid timezone '{tz_str}'. Use one of: {
                    ', '.join(self.get_timezones())}"
            )
        now = datetime.now(tz)
        return now

    def convert_utc_to_timezone(self, utc_dt: datetime, tz_str: str) -> datetime:
        """
        Convert a UTC datetime to the specified timezone.

        Args:
            utc_dt: datetime object (must be in UTC)
            tz_str: timezone string (e.g., 'GMT+5')

        Returns:
            datetime object in the specified timezone
        """
        if utc_dt is None:
            return None
            
        tz = self.timezones.get(tz_str)
        if not tz:
            return utc_dt  # return original if timezone is invalid
            
        if utc_dt.tzinfo is None:
            # If naive, assume it's UTC
            utc_dt = utc_dt.replace(tzinfo=timezone.utc)
        elif utc_dt.tzinfo != timezone.utc:
            # If not UTC, convert to UTC first
            utc_dt = utc_dt.astimezone(timezone.utc)
            
        return utc_dt.astimezone(tz)


if __name__ == "__main__":
    manager = UTCZoneManager()

    # print("Available Timezones:", manager.get_timezones())
    # print("Current date in UTC+4:", manager.get_current_date("GMT+4"))
    # print("Current date in UTC-7:", manager.get_current_date("GMT-7"))
