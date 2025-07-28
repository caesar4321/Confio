from django.core.management.base import BaseCommand
from users.models import User, UserAchievement, AchievementType, ConfioRewardBalance


class Command(BaseCommand):
    help = 'Debug user achievements for troubleshooting'

    def add_arguments(self, parser):
        parser.add_argument('username', type=str, help='Username to debug')

    def handle(self, *args, **options):
        username = options['username']
        
        try:
            user = User.objects.get(username=username)
        except User.DoesNotExist:
            self.stdout.write(self.style.ERROR(f'User "{username}" not found'))
            return
        
        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}'))
        self.stdout.write(self.style.SUCCESS(f'USER ACHIEVEMENT DEBUG FOR: {username}'))
        self.stdout.write(self.style.SUCCESS(f'{"="*60}\n'))
        
        # User info
        self.stdout.write(self.style.WARNING('USER INFO:'))
        self.stdout.write(f'  ID: {user.id}')
        self.stdout.write(f'  Username: {user.username}')
        self.stdout.write(f'  Email: {user.email}')
        self.stdout.write(f'  Firebase UID: {user.firebase_uid}')
        self.stdout.write(f'  Created: {user.created_at}')
        
        # Accounts
        from users.models import Account
        accounts = Account.objects.filter(user=user)
        self.stdout.write(f'\n  Accounts: {accounts.count()}')
        for acc in accounts:
            self.stdout.write(f'    - {acc.account_type}: {acc.account_id} (sui: {acc.sui_address[:20] if acc.sui_address else "None"}...)')
        
        # Achievement Types
        self.stdout.write(self.style.WARNING('\n\nACHIEVEMENT TYPES:'))
        types = AchievementType.objects.filter(is_active=True)
        self.stdout.write(f'  Total active types: {types.count()}')
        by_category = {}
        for t in types:
            if t.category not in by_category:
                by_category[t.category] = 0
            by_category[t.category] += 1
        for cat, count in by_category.items():
            self.stdout.write(f'    {cat}: {count}')
        
        # User Achievements
        self.stdout.write(self.style.WARNING('\n\nUSER ACHIEVEMENTS:'))
        achievements = UserAchievement.objects.filter(user=user).select_related('achievement_type')
        self.stdout.write(f'  Total: {achievements.count()}')
        
        # By status
        by_status = {
            'pending': [],
            'earned': [],
            'claimed': []
        }
        
        for ua in achievements:
            by_status[ua.status].append(ua)
        
        # Show earned
        self.stdout.write(self.style.SUCCESS(f'\n  EARNED ({len(by_status["earned"])}) - Ready to claim:'))
        for ua in by_status['earned']:
            self.stdout.write(
                f'    ✅ {ua.achievement_type.name} - '
                f'{ua.achievement_type.confio_reward} CONFIO '
                f'(earned: {ua.earned_at.strftime("%Y-%m-%d %H:%M") if ua.earned_at else "N/A"})'
            )
        
        # Show claimed
        self.stdout.write(self.style.SUCCESS(f'\n  CLAIMED ({len(by_status["claimed"])}) - Can share:'))
        for ua in by_status['claimed']:
            self.stdout.write(
                f'    💰 {ua.achievement_type.name} - '
                f'{ua.achievement_type.confio_reward} CONFIO '
                f'(claimed: {ua.claimed_at.strftime("%Y-%m-%d %H:%M") if ua.claimed_at else "N/A"})'
            )
        
        # Show pending (first 5)
        self.stdout.write(f'\n  PENDING ({len(by_status["pending"])}) - First 5:')
        for ua in by_status['pending'][:5]:
            self.stdout.write(
                f'    ⏳ {ua.achievement_type.name} - '
                f'{ua.achievement_type.confio_reward} CONFIO'
            )
        
        # CONFIO Balance
        self.stdout.write(self.style.WARNING('\n\nCONFIO BALANCE:'))
        try:
            balance = ConfioRewardBalance.objects.get(user=user)
            self.stdout.write(f'  Total Earned: {balance.total_earned} CONFIO')
            self.stdout.write(f'  Total Locked: {balance.total_locked} CONFIO')
            self.stdout.write(f'  USD Value: ${float(balance.total_locked)/4}')
        except ConfioRewardBalance.DoesNotExist:
            self.stdout.write('  No balance record')
        
        # GraphQL test
        self.stdout.write(self.style.WARNING('\n\nGRAPHQL QUERY TEST:'))
        self.stdout.write('  The userAchievements query filters by user=info.context.user')
        self.stdout.write('  Make sure you are logged in as this user in the app')
        self.stdout.write(f'  Expected results: {achievements.count()} total achievements')
        
        self.stdout.write(self.style.SUCCESS(f'\n{"="*60}\n'))