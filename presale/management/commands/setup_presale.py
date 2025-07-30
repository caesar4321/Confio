from django.core.management.base import BaseCommand
from django.utils import timezone
from decimal import Decimal
from presale.models import PresalePhase, PresaleStats


class Command(BaseCommand):
    help = 'Set up initial presale phases'

    def handle(self, *args, **options):
        # Phase 1: Raíces Fuertes
        phase1, created = PresalePhase.objects.get_or_create(
            phase_number=1,
            defaults={
                'name': 'Raíces Fuertes',
                'description': 'Fase inicial enfocada en Venezuela. Construyendo nuestra comunidad fundadora con el mejor precio.',
                'price_per_token': Decimal('0.25'),
                'goal_amount': Decimal('1000000'),  # $1M goal
                'min_purchase': Decimal('10'),
                'max_purchase': Decimal('1000'),
                'max_per_user': Decimal('5000'),  # Optional: $5k max per user for phase 1
                'status': 'active',  # Start with phase 1 active
                'start_date': timezone.now(),
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Phase 1: {phase1.name}'))
            # Create stats entry
            PresaleStats.objects.create(phase=phase1)
        else:
            self.stdout.write(self.style.WARNING(f'Phase 1 already exists: {phase1.name}'))
        
        # Phase 2: Expansión Regional
        phase2, created = PresalePhase.objects.get_or_create(
            phase_number=2,
            defaults={
                'name': 'Expansión Regional',
                'description': 'Llevando Confío a Argentina y más países hermanos de Latinoamérica.',
                'price_per_token': Decimal('0.50'),
                'goal_amount': Decimal('10000000'),  # $10M goal
                'min_purchase': Decimal('10'),
                'max_purchase': Decimal('5000'),
                'max_per_user': Decimal('25000'),  # Optional: $25k max per user for phase 2
                'status': 'upcoming',
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Phase 2: {phase2.name}'))
            # Create stats entry
            PresaleStats.objects.create(phase=phase2)
        else:
            self.stdout.write(self.style.WARNING(f'Phase 2 already exists: {phase2.name}'))
        
        # Phase 3: Alcance Continental
        phase3, created = PresalePhase.objects.get_or_create(
            phase_number=3,
            defaults={
                'name': 'Alcance Continental',
                'description': 'Confío conquista América con el respaldo de inversores internacionales.',
                'price_per_token': Decimal('1.00'),
                'goal_amount': Decimal('50000000'),  # $50M goal (TBD)
                'min_purchase': Decimal('10'),
                'max_purchase': Decimal('10000'),
                'max_per_user': None,  # No limit for phase 3
                'status': 'upcoming',
            }
        )
        
        if created:
            self.stdout.write(self.style.SUCCESS(f'Created Phase 3: {phase3.name}'))
            # Create stats entry
            PresaleStats.objects.create(phase=phase3)
        else:
            self.stdout.write(self.style.WARNING(f'Phase 3 already exists: {phase3.name}'))
        
        self.stdout.write(self.style.SUCCESS('Presale setup completed!'))