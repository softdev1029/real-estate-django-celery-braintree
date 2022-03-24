from django.contrib.auth import get_user_model
from django.core.validators import MinValueValidator
from django.db import models

__all__ = 'AbstractNote', 'AbstractTag', 'SingletonModel'

User = get_user_model()


class AbstractNote(models.Model):
    """
    Abstract model for note models.
    """
    created_by = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)
    text = models.TextField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ('-created_date',)


class AbstractTag(models.Model):
    """
    Abstract model to contain the fields and functionality of our general tag structure.
    """
    company = models.ForeignKey('sherpa.Company', on_delete=models.CASCADE)
    name = models.CharField(max_length=32)
    is_custom = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    order = models.IntegerField(default=1, validators=[MinValueValidator(1)])

    class Meta:
        unique_together = ('company', 'name')
        ordering = ('order',)
        abstract = True

    def __str__(self):
        return f'{self.company.name} - {self.name}'


class SingletonModel(models.Model):
    """
    Use to create Singleton models.
    """
    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = 1
        super(SingletonModel, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        pass

    @classmethod
    def load(cls):
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
