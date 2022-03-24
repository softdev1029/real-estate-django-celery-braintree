from random import randint

from django.db.models import F, Q
from django.utils import timezone

from core import models
from .managers import CarrierApprovedTemplateManager


class SMSResult(models.Model):
    """
    Store data about a status result for our outgoing messages.

    - The data from the webhook can be defined by telnyx webhook documentation[0].
    - Should only store data about the result, *not* about the message itself (i.e. prospect, text)

    [0] https://developers.telnyx.com/docs/v2/development/api-guide/webhooks
    """
    class Status:
        SENT = 'sent'
        DELIVERED = 'delivered'
        DELIVERY_FAILED = 'delivery_failed'
        DELIVERY_UNCONFIRMED = 'delivery_unconfirmed'
        SENDING_FAILED = 'sending_failed'

        CHOICES = (
            (SENT, 'Sent'),
            (DELIVERED, 'Delivered'),
            (DELIVERY_FAILED, 'Delivery Failed'),
            (DELIVERY_UNCONFIRMED, 'Delivery Unconfirmed'),
            (SENDING_FAILED, 'Sending Failed'),
        )

    sms = models.OneToOneField('sherpa.SMSMessage', on_delete=models.CASCADE, related_name='result')

    created = models.DateTimeField(auto_now_add=True, db_index=True)

    # Can view the telnyx error codes: https://developers.telnyx.com/docs/api/v2/overview#errors
    error_code = models.CharField(max_length=16, blank=True, db_index=True)

    # For status, we'll need to normalize the data when receiving the webhook.
    # telnyx statuses: https://developers.telnyx.com/docs/v2/messaging/message-detail-records#mdr-schema-and-status-descriptions  # noqa:E501
    # twilio statuses: https://support.twilio.com/hc/en-us/articles/223134347-What-are-the-Possible-SMS-and-MMS-Message-Statuses-and-What-do-They-Mean-  # noqa:E501
    status = models.CharField(max_length=32, choices=Status.CHOICES, db_index=True)

    @property
    def provider(self):
        return self.phone_number.provider

    @property
    def delay(self):
        """
        Calculate the time in seconds that was in between the message creation and when the result
        was received.
        """
        delta = self.created - self.sms.dt
        return delta.seconds


class DailySMSHistory(models.Model):
    """
    Historical data to show the amount of errors, delivery rate, sent, and other stats,
    """
    date = models.DateField(unique=True)
    total_attempted = models.PositiveIntegerField()
    total_delivered = models.PositiveIntegerField()
    total_error = models.PositiveIntegerField()

    def __str__(self):
        return str(self.date)

    class Meta:
        ordering = ('-date',)
        verbose_name_plural = 'Daily SMS history'

    @property
    def delivery_rate(self):
        if not self.total_attempted:
            return 0

        return round(self.total_delivered / self.total_attempted * 100)

    @property
    def error_rate(self):
        if not self.total_attempted:
            return 0

        return round(self.total_error / self.total_attempted * 100)

    @staticmethod
    def gather_for_day(date):
        """
        Gather and save the stats for a given date.

        :date datetime.date: Date object for the date that should be gathered.
        """
        # Base queryset that returns all the results for the day.
        daily_qs = SMSResult.objects.filter(created__date=date)

        total_attempted = daily_qs.count()
        total_delivered = daily_qs.filter(status=SMSResult.Status.DELIVERED).count()

        # There are a couple statuses that signify an error
        delivery_failed_list = [SMSResult.Status.DELIVERY_FAILED, SMSResult.Status.SENDING_FAILED]
        total_error = daily_qs.filter(status__in=delivery_failed_list).count()

        DailySMSHistory.objects.update_or_create(
            date=date,
            defaults={
                'total_attempted': total_attempted,
                'total_delivered': total_delivered,
                'total_error': total_error,
            },
        )


class CarrierApprovedTemplate(models.Model):
    """
    Carrier-approved Templates are similar to SMSTemplates with the added bonus of having been
    verified by SMS carriers once active.

    Templates can be preloaded while awaiting verification.

    DEPRECATED: All functionality around carrier-approved templates is being removed in favor of
        allowing custom templates but enforcing identification and opt out language.
    """
    message = models.TextField(max_length=300)
    alternate_message = models.TextField(
        max_length=300,
        null=True,
        blank=True,
        help_text='If not provided, will randomly select an alternate message from database.')
    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=False)
    created = models.DateTimeField(auto_now_add=True)
    verified = models.DateTimeField(null=True, blank=True)

    objects = CarrierApprovedTemplateManager()

    class Meta:
        ordering = ('-is_verified', '-is_active', 'created')

    def save(self, *args, **kwargs):
        if self.is_verified and not self.verified:
            self.verified = timezone.now()

        if not self.alternate_message:
            # If a template is created without an alternate message, we will randomly select
            # one from the current templates.
            count = CarrierApprovedTemplate.objects.exclude(
                Q(alternate_message__isnull=True) | Q(alternate_message__exact=''),
            ).count()

            random_index = randint(0, count - 1)
            random_template = CarrierApprovedTemplate.objects.all()[random_index]
            self.alternate_message = random_template.alternate_message

        super().save(*args, **kwargs)


class SMSTemplateCategory(models.Model):
    """
    Allow companies to group their templates together to use in certain situations for campaigns.
    """
    company = models.ForeignKey(
        'sherpa.Company',
        on_delete=models.CASCADE,
        related_name='template_categories',
    )
    title = models.CharField(max_length=32)
    is_custom = models.BooleanField(default=False)

    class Meta:
        unique_together = ('company', 'title')

    @property
    def active_templates(self):
        return self.smstemplate_set.filter(is_active=True).order_by('sort_order')

    @property
    def first_template(self):
        return self.active_templates.first()

    @property
    def last_template(self):
        return self.active_templates.last()

    @property
    def max_order(self):
        if self.last_template:
            return self.last_template.sort_order
        return 0

    def next_template(self, current_template):
        """
        Returns the next template based on order from the current template in the category.

        :param current_template SMSTemplate: The current template which will determine the next.
        """
        active_templates = self.active_templates.order_by("id")
        template = active_templates.filter(
            id__gt=current_template.id,
        ).first()
        if not template:
            template = active_templates.first()

        return template or current_template

    def prev_template(self, current_template):
        """
        Returns the previous template based on order from the current template in the category.

        :param current_template SMSTemplate: The current template which will determine the next.
        """
        active_templates = self.active_templates.order_by("id")
        template = active_templates.filter(
            id__lt=current_template.id,
        ).first()
        if not template:
            template = active_templates.last()

        return template or current_template

    def set_order(self, template, order, from_new=False):
        """
        Sets the order of the template moving other templates in the category.

        :param template SMSTemplate: The template being updated.
        :param order int: The new order to set the template to.
        :param from_new bool: Determines if the order is due to a category change.
        """
        move = -1 if template.sort_order < order else 1
        num = self.max_order + 1 if from_new else order
        templates_to_resort = self.active_templates.filter(
            sort_order__range=(min(template.sort_order, num), max(template.sort_order, num)),
        ).exclude(id=template.id)

        for t in templates_to_resort:
            t.sort_order = F('sort_order') + move
            t.save(update_fields=['sort_order'])

        template.sort_order = order
        template.save(update_fields=['sort_order'])

    def reset_order(self):
        """
        Refreshes the order of the underlying templates in the event of removing templates
        and creating holes.
        """
        for i, template in enumerate(self.active_templates):
            template.sort_order = i + 1
            template.save(update_fields=['sort_order'])

    def template_moved(self, sort_order):
        """
        After a template is moved out of the category a hole could form at the old sort order.

        :param sort_order int: The sort order value of the moved template.
        """
        templates_to_update = self.active_templates.filter(sort_order__gt=sort_order)
        if not templates_to_update.exists():
            # Template that moved was at the end.
            return

        for template in templates_to_update:
            template.sort_order = sort_order
            template.save(update_fields=['sort_order'])
            sort_order += 1
