from django.core.management.base import BaseCommand
from presale.models import PresalePhase


class Command(BaseCommand):
    help = 'Update presale phases with complete data matching UI'

    def handle(self, *args, **options):
        # Phase 1 data
        phase1 = PresalePhase.objects.filter(phase_number=1).first()
        if phase1:
            phase1.target_audience = 'Comunidad base'
            phase1.location_emoji = '🌱 Donde todo comienza'
            phase1.vision_points = ['Tu dinero más seguro', 'Pagos instantáneos', 'Comunidad sólida']
            phase1.save()
            self.stdout.write(self.style.SUCCESS('Updated Phase 1'))
        
        # Phase 2 data
        phase2 = PresalePhase.objects.filter(phase_number=2).first()
        if phase2:
            phase2.target_audience = 'Nuevos mercados'
            phase2.location_emoji = '🌎 Creciendo juntos'
            phase2.vision_points = ['Red entre países', 'Más oportunidades', 'Economía conectada']
            phase2.save()
            self.stdout.write(self.style.SUCCESS('Updated Phase 2'))
        
        # Phase 3 data
        phase3 = PresalePhase.objects.filter(phase_number=3).first()
        if phase3:
            phase3.target_audience = 'Inversores globales'
            phase3.location_emoji = '🌎 Todo el continente'
            phase3.vision_points = ['Presencia continental', 'Inversión internacional', 'Liderazgo regional']
            phase3.save()
            self.stdout.write(self.style.SUCCESS('Updated Phase 3'))
        
        self.stdout.write(self.style.SUCCESS('All phases updated with complete data!'))