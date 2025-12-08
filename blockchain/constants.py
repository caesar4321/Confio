from decimal import Decimal

REFERRAL_ACHIEVEMENT_SLUGS = {'successful_referral', 'llegaste_por_influencer'}
REFERRAL_DAILY_LIMIT = Decimal('10')
REFERRAL_WEEKLY_LIMIT = Decimal('50')
REFERRAL_SINGLE_REVIEW_THRESHOLD = Decimal('500')
REFERRAL_VERIFICATION_TRIGGER = Decimal('100')
REFERRAL_MAX_USERS_PER_IP = 3
