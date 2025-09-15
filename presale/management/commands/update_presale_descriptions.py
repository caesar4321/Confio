from django.core.management.base import BaseCommand
from presale.models import PresalePhase


class Command(BaseCommand):
    help = 'Update presale phase descriptions to match UI'

    def handle(self, *args, **options):
        # Update Phase 1
        phase1 = PresalePhase.objects.filter(phase_number=1).first()
        if phase1:
            phase1.description = 'Fortaleciendo nuestra comunidad fundadora con el mejor precio. Donde todo comienza 🌱'
            phase1.save()
            self.stdout.write(self.style.SUCCESS(f'Updated Phase 1 description'))
        
        # Update Phase 2
        phase2 = PresalePhase.objects.filter(phase_number=2).first()
        if phase2:
            phase2.description = 'Llevando Confío a más países hermanos de Latinoamérica. Creciendo juntos 🌎'
            phase2.save()
            self.stdout.write(self.style.SUCCESS(f'Updated Phase 2 description'))
        
        # Update Phase 3 (LatAm focus)
        phase3 = PresalePhase.objects.filter(phase_number=3).first()
        if phase3:
            phase3.description = 'Confío crece en Latinoamérica con el respaldo de la comunidad. Todo el continente 🌎'
            phase3.save()
            self.stdout.write(self.style.SUCCESS(f'Updated Phase 3 description'))
        
        self.stdout.write(self.style.SUCCESS('All descriptions updated!'))
