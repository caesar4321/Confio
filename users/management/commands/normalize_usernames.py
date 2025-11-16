from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from users.validators import validate_username
from users.utils_username import generate_compliant_username


class Command(BaseCommand):
    help = "Normalize existing usernames to match UI policy (<=20 chars, alphanumeric + underscore)."

    def handle(self, *args, **options):
        User = get_user_model()
        updated = 0
        for user in User.all_objects.all():
            username = user.username or ""
            is_valid, _ = validate_username(username)
            if is_valid:
                continue
            new_username = generate_compliant_username(username or user.email or user.firebase_uid, exclude_user_id=user.id)
            self.stdout.write(f"Updating user {user.id}: '{username}' -> '{new_username}'")
            user.username = new_username
            user.save(update_fields=["username"])
            updated += 1
        self.stdout.write(self.style.SUCCESS(f"Normalized {updated} usernames."))
