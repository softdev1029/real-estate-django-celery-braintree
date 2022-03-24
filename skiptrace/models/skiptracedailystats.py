from core import models


class SkipTraceDailyStats(models.Model):
    """
    Record usage stats for skip trace aggregated by day.
    """
    date = models.DateField(unique=True)
    total_external_hits = models.PositiveIntegerField()
    total_internal_hits = models.PositiveIntegerField()

    class Meta:
        verbose_name_plural = 'Skip trace daily stats'
        ordering = ('-date',)

    def __str__(self):
        return str(self.date)

    def total_hits(self):
        return self.total_external_hits + self.total_internal_hits
