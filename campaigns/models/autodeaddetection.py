from core import models


class AutoDeadDetection(models.Model):
    """
    Store the results of our auto-dead detection model.
    """
    created = models.DateTimeField(auto_now_add=True)
    message = models.CharField(max_length=512, blank=True)
    marked_auto_dead = models.BooleanField()
    score = models.DecimalField(max_digits=5, decimal_places=3)

    class Meta:
        ordering = ('-created',)
