from django.conf import settings
from django.db import models


class ReviewAccess(models.Model):
    """A store-review account switched to a country by the review deep link
    (users/review_access.py). Rows are never deleted: re-applying supersedes
    the previous one, so the monthly cap counts every grant."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='review_accesses')
    country = models.CharField(max_length=2)
    # Argentina: every geo policy passes. US/UK: none does (they show the blocks).
    geo_exempt = models.BooleanField(default=False)
    # The account's country before its first review grant, restored when access ends.
    country_before_review = models.CharField(max_length=2, blank=True, null=True)
    source_before_review = models.CharField(max_length=16, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    expires_at = models.DateTimeField()
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=['user', 'superseded_at'], name='review_access_user_active')]

    def __str__(self):
        return f'{self.user_id} → {self.country}{" (exempt)" if self.geo_exempt else ""}'
