from core import models


class BTBase(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    created_at = models.DateTimeField()
    updated_at = models.DateTimeField()

    class Meta:
        abstract = True
