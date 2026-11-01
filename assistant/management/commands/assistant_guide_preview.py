"""Show a test account one step of the first-steps guide.

    manage.py assistant_guide_preview 5 top_up
    manage.py assistant_guide_preview 5 --clear

Restart the app after each change: a card opens once per session.
"""
from django.core.management.base import BaseCommand, CommandError

from assistant import guide


class Command(BaseCommand):
    help = 'Force a guide step on a test account'

    def add_arguments(self, parser):
        parser.add_argument('user_id', type=int)
        parser.add_argument('step', nargs='?', choices=sorted(guide.STEPS))
        parser.add_argument('--clear', action='store_true')

    def handle(self, *args, user_id, step, clear, **options):
        if not clear and not step:
            raise CommandError('Name a step or pass --clear')
        try:
            guide.set_preview(user_id, None if clear else step)
        except ValueError as exc:
            raise CommandError(str(exc))
        self.stdout.write(f'{user_id}: {"normal guide" if clear else step}')
