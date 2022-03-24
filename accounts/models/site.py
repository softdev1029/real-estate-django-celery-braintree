from core import models
from sherpa.abstracts import SingletonModel

__all__ = (
    'FeatureNotification', 'Features', 'SiteSettings', 'SupportLink',
)


class Features(models.Model):
    """
    Features available to users.
    """
    TEXTING = 'texting'
    SKIP_TRACE = 'skip_trace'
    LIST_STACKING = 'list_stacking'
    DIRECT_MAIL = 'direct_mail'

    CHOICES = (
        (TEXTING, 'Texting'),
        (SKIP_TRACE, 'Skip Trace'),
        (LIST_STACKING, 'List Stacking'),
        (DIRECT_MAIL, 'Direct Mail'),
    )
    name = models.CharField(max_length=20, choices=CHOICES, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        app_label = 'sherpa'


class FeatureNotification(models.Model):
    """
    Generic feature notifications.
    """
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    image_path = models.FileField(null=True, blank=True)
    url = models.URLField(blank=True)
    header_copy = models.CharField(max_length=255, blank=True)
    body_copy = models.CharField(max_length=255, blank=True)
    button_text = models.CharField(max_length=255, blank=True)
    button_link = models.CharField(max_length=255, blank=True)
    display_amount = models.IntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_dt = models.DateTimeField(auto_now_add=True)
    updated_dt = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        app_label = 'sherpa'


class SiteSettings(SingletonModel):
    """
    Model to hold Site Settings.
    """
    direct_mail_drop_date_hours = models.IntegerField(default=48)
    smarty_streets_nightly_run_count = models.IntegerField(default=5000000)

    class Meta:
        app_label = 'sherpa'


class SupportLink(models.Model):
    """
    Data controlled support links allowing for updating by admin users.
    """
    title = models.CharField(max_length=32)
    description = models.CharField(max_length=128)
    icon = models.CharField(max_length=32, blank=True)
    url = models.URLField(blank=True)

    class Meta:
        app_label = 'sherpa'
        ordering = ('id',)

    def __str__(self):
        return self.title
