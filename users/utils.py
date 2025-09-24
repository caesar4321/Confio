from django.utils import timezone
from django.db.utils import ProgrammingError, OperationalError
from .models import User


def touch_user_activity(user_id, when=None):
    """Best-effort update of user's last_activity_at.

    Safe before migrations: swallows missing-column errors.
    """
    when = when or timezone.now()
    try:
        if user_id:
            User.objects.filter(id=user_id).update(last_activity_at=when)
    except (ProgrammingError, OperationalError):
        # Column may not exist yet if migrations aren't applied
        pass

