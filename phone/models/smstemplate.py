import re

from model_utils import FieldTracker

from django.contrib.auth import get_user_model
from django.utils import timezone as django_tz

from accounts.models.company import Company
from core import models
from core.mixins import SortOrderModelMixin
from sms.utils import all_tags_valid, find_banned_words, find_spam_words, has_tag
from .smsmessage import SMSMessage

__all__ = (
    'SMSPrefillText', 'SMSTemplate',
)

User = get_user_model()


class SMSTemplate(models.Model):
    """
    Templates to use during bulk sending to prospects.

    The message can be populated with template tags, which will later populate that data from the
    prospect to be the actual sms message content that is sent out.
    """
    company = models.ForeignKey(Company, null=True, blank=True, on_delete=models.CASCADE)
    created_by = models.ForeignKey(User, null=True, on_delete=models.CASCADE)
    category = models.ForeignKey(
        'sms.SMSTemplateCategory', null=True, blank=True, on_delete=models.SET_NULL)

    template_name = models.CharField(max_length=255)
    is_active = models.BooleanField(default=True)
    created = models.DateTimeField(auto_now_add=True)
    last_updated = models.DateTimeField(null=True, blank=True)
    message = models.CharField(max_length=320)
    alternate_message = models.CharField(max_length=320)
    sort_order = models.IntegerField(default=0)
    delivery_percent = models.PositiveSmallIntegerField(null=True, blank=True)
    response_rate = models.PositiveSmallIntegerField(null=True, blank=True)

    tracker = FieldTracker(fields=[
        'category_id', 'template_name', 'message', 'alternate_message', 'sort_order',
    ])

    class Meta:
        app_label = 'sherpa'
        ordering = ('sort_order',)

    def __str__(self):
        return self.template_name

    def save(self, *args, **kwargs):
        if self.company.default_alternate_message and not self.alternate_message:
            self.alternate_message = self.company.default_alternate_message
        changed = any([
            self.tracker.has_changed('category_id'),
            self.tracker.has_changed('template_name'),
            self.tracker.has_changed('message'),
            self.tracker.has_changed('alternate_message'),
        ])
        if self.category and self.sort_order == 0:
            self.sort_order = self.category.max_order + 1
        if changed:
            self.last_updated = django_tz.now()

        return super(SMSTemplate, self).save(*args, **kwargs)

    @property
    def is_valid(self):
        """
        Boolean that determines if the sms template is valid for sending.
        """
        conditions = [
            all_tags_valid(self.message),
            self.has_required_outgoing_tags,
            len(find_banned_words(self.message)) == 0,
            len(find_spam_words(self.message)) == 0,
        ]
        return all(conditions)

    @property
    def has_required_outgoing_tags(self):
        """
        Determine if a template has all the required outgoing tags.
        """
        tag = 'CompanyName'
        return has_tag(self.message, tag) and has_tag(self.alternate_message, tag)

    @property
    def is_invalid(self):
        """
        Check to see if template has invalid formatting.
        """
        check = [
            not all_tags_valid(self.message),
            len(find_banned_words(self.message)) > 0,
            len(find_spam_words(self.message)) > 0,
        ]
        return any(check)

    @staticmethod
    def valid_templates(company):
        """
        DEPRECATED: This is only used in an endpoint, which is not used.

        Return all active templates for a company that pass the blocked words filtering. These
        templates are considered valid to select for messaging prospects.
        """
        sms_template_list = SMSTemplate.objects.filter(
            company=company,
            is_active=True,
        ).order_by('-created')
        valid_templates = []
        for template in sms_template_list:
            if not template.banned_words:
                valid_templates.append(template)

        return valid_templates

    @property
    def banned_words(self):
        """
        Check if template contains banned words.

        :return: Array of banned words in the template.
        """
        message = self.message or ''
        alternate_message = self.alternate_message or ''

        replace_chars = ['.', ',', '-']
        for char in replace_chars:
            message = message.replace(char, ' ')
            alternate_message = alternate_message.replace(char, ' ')

        banned_1 = find_banned_words(message) + find_spam_words(message)
        banned_2 = find_banned_words(alternate_message) + find_spam_words(alternate_message)
        return banned_1 + banned_2

    def copy_alternate_message(self, message):
        """
        Copy alternate message to `Company`'s default alternate message.
        """
        self.alternate_message = message
        self.save(update_fields=['alternate_message'])
        self.company.default_alternate_message = self.alternate_message
        self.company.save(update_fields=['default_alternate_message'])

    def get_alternate_message(self, is_carrier_approved: bool = False, opt_out_language: str = ""):
        """
        Return string of what the alternate message should be for a template.
        """
        if is_carrier_approved:
            # DEPRECATED
            # We need to get the alternate carrier-approved message as we need to format it
            # like the normal messages.
            raise Exception('Carrier approved templates no longer supported.')

        message = self.alternate_message
        match = re.findall(r'(?<=\{CompanyName:)([^]]*?)(?=\})', message)
        if match:
            found_index = match[0]
            i = int(match[0]) if match[0].isnumeric() else 0
            if i >= len(self.company.outgoing_company_names):
                i = 0
            company_name = self.company.outgoing_company_names[i]
            tag = '{CompanyName:' + found_index + '}'
            message = message.replace(tag, company_name)

        return message.replace(
            '{CompanyName}',
            self.company.random_outgoing_company_name,
        ) + opt_out_language

    def get_delivery_percent(self):
        """
        Returns an integer percentage of how many of the template's messages were delivered, or None
        if there are no results for the template.
        """
        from sms.models import SMSResult

        messages = self.smsmessage_set.all()
        results = SMSResult.objects.filter(sms__in=messages)

        try:
            delivered = results.filter(status=SMSResult.Status.DELIVERED)
            return int(delivered.count() / results.count() * 100)
        except ZeroDivisionError:
            return None

    def get_response_rate(self):
        """
        Returns an integer percentage of how many of the template's initial messages have received
        a response, or None if the template has not sent any messages.
        """
        message_count = self.smsmessage_set.count()
        if not message_count:
            return None

        response_count = SMSMessage.objects.filter(
            prospect__in=self.smsmessage_set.exclude(
                prospect__opted_out=True,
            ).values_list('prospect_id', flat=True),
            from_prospect=True,
        ).count()

        return int(response_count / message_count * 100)


class SMSPrefillText(SortOrderModelMixin, models.Model):
    """
    Companies can have certain canned replies to quickly respond to commonly seen messages from
    prospects.
    """
    company = models.ForeignKey(
        Company, null=True, blank=True, related_name="quick_replies", on_delete=models.CASCADE)
    question = models.CharField(max_length=160, blank=True)
    message = models.CharField(max_length=500, blank=True)
    sort_order = models.IntegerField(default=0)

    # message_formatted is left blank and is used in the object with editing
    # TODO: (aww20190821) there are no records in production that are using message_formatted.
    message_formatted = models.CharField(max_length=500, blank=True)

    def is_invalid(self):
        """
        Check to see if quick reply has invalid formatting.
        """
        return not all_tags_valid(self.message)

    def get_sortable_queryset(self):
        """
        Returns the queryset of sortable instances.
        """
        if not self.company:
            return SMSPrefillText.objects.none()
        return self.company.quick_replies.all()

    class Meta(SortOrderModelMixin.Meta):
        app_label = 'sherpa'
