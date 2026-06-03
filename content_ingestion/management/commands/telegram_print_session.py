import asyncio
import getpass

from django.core.management.base import BaseCommand, CommandError

from content_ingestion.telegram_client import get_client


class Command(BaseCommand):
    help = 'Interactively log in to Telegram and print a reusable TELEGRAM_SESSION_STRING.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--phone',
            help='Phone number in international format, for example +12064230127.',
        )

    def handle(self, *args, **options):
        try:
            session_string = asyncio.run(self._login(options.get('phone')))
            self.stdout.write(self.style.SUCCESS('Logged in. Store this value as TELEGRAM_SESSION_STRING:'))
            self.stdout.write(session_string)
        except Exception as exc:
            raise CommandError(str(exc)) from exc

    async def _login(self, phone):
        self.stdout.write('Creating Telegram client...')
        client = get_client()
        self.stdout.write('Connecting to Telegram...')
        await client.connect()
        try:
            if not await client.is_user_authorized():
                phone = phone or input('Telegram phone (+countrycode...): ').strip()
                self.stdout.write(f'Sending Telegram login code to {phone}...')
                await client.send_code_request(phone)
                code = input('Telegram code: ').strip()

                try:
                    await client.sign_in(phone=phone, code=code)
                except Exception as exc:
                    try:
                        from telethon.errors import SessionPasswordNeededError
                    except ImportError:
                        raise
                    if not isinstance(exc, SessionPasswordNeededError):
                        raise
                    password = getpass.getpass('Telegram 2FA password: ')
                    await client.sign_in(password=password)

            session_string = client.session.save()
            if session_string:
                return session_string

            from telethon.sessions import StringSession

            return StringSession.save(client.session)
        finally:
            await client.disconnect()
