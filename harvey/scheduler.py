import random
from datetime import datetime, timezone, timedelta
import pytz

def get_prospect_timezone_info(location: str = "", company: str = "", email: str = ""):
    """Determine prospect timezone and business hours boundaries."""
    loc = ((location or "") + " " + (company or "")).lower()
    em = (email or "").lower()

    if any(k in loc for k in ("dubai", "uae", "abu dhabi", "sharjah", "emirates")) or em.endswith(".ae"):
        return pytz.timezone("Asia/Dubai"), "Dubai (GST)", 10, 17 # 10:00 AM - 5:00 PM GST
    elif any(k in loc for k in ("india", "gurgaon", "delhi", "mumbai", "bangalore", "noida", "hyderabad", "chennai")) or em.endswith(".in"):
        return pytz.timezone("Asia/Kolkata"), "India (IST)", 10, 18 # 10:00 AM - 6:00 PM IST
    elif any(k in loc for k in ("london", "uk", "united kingdom", "manchester", "birmingham")) or em.endswith(".uk") or em.endswith(".co.uk"):
        return pytz.timezone("Europe/London"), "UK (BST)", 9, 17 # 9:30 AM - 5:00 PM BST
    elif any(k in loc for k in ("miami", "austin", "dallas", "new york", "texas", "florida", "ny", "tx", "fl", "usa", "united states")) or em.endswith(".us"):
        return pytz.timezone("America/New_York"), "US East (EST)", 9, 17 # 9:00 AM - 5:00 PM EST
    else:
        # Default global to India/Dubai working hours (10 AM to 6 PM IST)
        return pytz.timezone("Asia/Kolkata"), "Global (IST)", 10, 18


def check_prospect_working_hours(location: str = "", company: str = "", email: str = "") -> tuple[bool, str, datetime]:
    """
    Check if current time is inside recipient's local business working hours.
    Returns:
        (is_in_slot: bool, reason: str, next_slot_utc: datetime)
    """
    tz, label, start_hour, end_hour = get_prospect_timezone_info(location, company, email)
    now_local = datetime.now(tz)
    local_hour = now_local.hour + (now_local.minute / 60.0)
    weekday = now_local.weekday() # 0 = Monday, 6 = Sunday
    is_workday = weekday < 6 # Monday - Saturday (Real estate, clinics & agencies active on Saturday)

    if is_workday and (start_hour <= local_hour < end_hour):
        # Currently inside prime business hours
        return True, f"{label} prime hours ({now_local.strftime('%I:%M %p')})", datetime.now(timezone.utc).replace(tzinfo=None)

    # Calculate next upcoming business slot
    if is_workday and local_hour < start_hour:
        # Later today
        target_local = now_local.replace(hour=start_hour, minute=random.randint(5, 25), second=0, microsecond=0)
    else:
        # Next business day
        days_ahead = 1
        if weekday == 5: # Saturday night -> Monday
            days_ahead = 2
        elif weekday == 6: # Sunday -> Monday
            days_ahead = 1
        target_local = (now_local + timedelta(days=days_ahead)).replace(hour=start_hour, minute=random.randint(5, 25), second=0, microsecond=0)

    # Convert to UTC naive datetime for SQLite storage
    next_slot_utc = target_local.astimezone(pytz.utc).replace(tzinfo=None)
    time_str = now_local.strftime("%I:%M %p")
    return False, f"{label} off-hours ({time_str})", next_slot_utc
