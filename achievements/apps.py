from django.apps import AppConfig


class AchievementsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'achievements'
    verbose_name = 'Referrals & Rewards'
    
    def ready(self):
        import achievements.signals
