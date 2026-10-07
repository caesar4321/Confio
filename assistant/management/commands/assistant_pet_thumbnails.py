"""Make the small display copy of every existing custom pet (pets created
since 2026-10-07 get one at creation). Safe to rerun: existing thumbnails
are skipped.

    manage.py assistant_pet_thumbnails
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Create missing thumbnails for custom assistant pets.'

    def handle(self, *args, **opts):
        from assistant import pets
        from assistant.models import CustomPet

        done = fallback = 0
        for pet in CustomPet.objects.filter(deleted_at__isnull=True).exclude(image_key='').iterator():
            if pets._display_key(pet) == pets.thumb_key(pet.image_key):
                done += 1
            else:
                fallback += 1
        self.stdout.write(f'{done} pets have a thumbnail; {fallback} still serve the original')
