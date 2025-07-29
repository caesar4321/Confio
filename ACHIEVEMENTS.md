# Confío Achievement System (Logros)

## Overview

The Confío achievement system rewards users with CONFIO tokens for completing specific actions within the app. The system is designed to encourage user engagement, P2P trading, and referrals.

## Active Achievements (MVP)

### 1. Pionero Beta (1 CONFIO)
- **Description**: Únete durante la fase beta
- **Trigger**: Automatically awarded on user signup
- **Limit**: Only the first 10,000 users
- **Implementation**: `users/signals.py` - `create_welcome_achievement`

### 2. Conexión Exitosa (4 CONFIO) 
- **Description**: Registra quién te invitó a Confío
- **Trigger**: When user sets their referrer (influencer or friend)
- **Implementation**: `users/referral_mutations.py` - `SetReferrer` mutation

### 3. Primera Compra P2P (8 CONFIO)
- **Description**: Completa tu primera compra P2P
- **Trigger**: When user completes their first P2P trade (status = COMPLETED)
- **Implementation**: `users/signals.py` - `handle_p2p_trade_achievements`

### 4. 10 Intercambios (20 CONFIO)
- **Description**: Completa 10 intercambios P2P
- **Trigger**: After 10 completed P2P trades (status = COMPLETED)
- **Implementation**: `users/signals.py` - `handle_p2p_trade_achievements`

### 5. Referido Exitoso (4 CONFIO)
- **Description**: Tu referido hizo su primera transacción
- **Trigger**: When a referred user completes their first P2P trade
- **Implementation**: `users/signals.py` - `check_referral_achievement`

### 6. Hodler 30 días (12 CONFIO)
- **Description**: Mantén CONFIO por 30 días
- **Trigger**: Daily Celery task checks users who have held CONFIO for 30 days
- **Implementation**: `users/tasks.py` - `check_hodler_achievements`

## Technical Implementation

### Database Models

- **AchievementType**: Defines available achievements
- **UserAchievement**: Tracks which users have earned which achievements
- **InfluencerReferral**: Tracks referral relationships

### Achievement States

1. **earned**: User has completed the requirement
2. **claimed**: User has claimed the CONFIO reward

### Automatic Triggers

Most achievements are triggered automatically through Django signals:

```python
# Example: P2P Trade Achievement
@receiver(post_save, sender=P2PTrade)
def handle_p2p_trade_achievements(sender, instance, created, **kwargs):
    if instance.status == 'COMPLETED':
        # Award achievements...
```

### Celery Tasks

For time-based achievements, use Celery beat schedule:

```python
CELERY_BEAT_SCHEDULE = {
    'check-hodler-achievements': {
        'task': 'users.check_hodler_achievements',
        'schedule': crontab(hour=0, minute=0),  # Daily at midnight
    },
}
```

## Management Commands

### Test Achievement System
```bash
myvenv/bin/python manage.py test_achievements
```

### Check Hodler Achievements (Manual)
```bash
myvenv/bin/python manage.py check_hodler_achievements
```

### Simplify Achievements (Migration)
```bash
myvenv/bin/python manage.py final_simplify_achievements
```

## Future Considerations

1. **Achievement Tiers**: Could add bronze/silver/gold tiers for trading volume
2. **Regional Achievements**: Country-specific achievements
3. **Merchant Achievements**: For business accounts
4. **Seasonal Achievements**: Time-limited campaigns

## Security Notes

- Achievements cannot be manually awarded (except by admin)
- Each achievement can only be earned once per user
- Referral achievements have anti-abuse checks
- 10,000 user limit on Pionero Beta prevents token inflation