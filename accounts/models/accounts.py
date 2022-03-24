from datetime import date, datetime, time, timedelta
from functools import reduce
import logging
import math
from operator import or_ as OR

import pytz

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db.models import Avg, Count, Q
from django.db.models.functions import Lower, TruncDate, TruncTime
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone as django_tz
from django.utils.functional import cached_property

from core import models
from skiptrace.models import UploadSkipTrace
from .site import FeatureNotification

logger = logging.getLogger(__name__)

__all__ = (
    'create_profile',
    'UserProfile',
    'UserFeatureNotification',
)

User = get_user_model()


class UserProfileQuerySet(models.QuerySet):

    def valid(self):
        """ Return a QS of account users pre-filtered to those allowed without knowledge of Company
        membership. """
        all_users = User.objects.all()
        non_staff_users = all_users.filter(is_staff=False)
        duplicate_emails = [
            u['email_lower']
            for u in User.objects.
                annotate(email_lower=Lower('email')).
                values('email_lower').
                annotate(email_ct=Count('email_lower')).
                values('email_lower', 'email_ct').
                filter(email_ct__gt=1)
        ]
        iexact_email_filter = reduce(OR, (Q(email__iexact=email) for email in duplicate_emails))
        users_unique_emails = non_staff_users.exclude(iexact_email_filter)
        non_unique_email_ct = non_staff_users.count() - users_unique_emails.count()
        logger.info(f'[ch15688] filtered {non_unique_email_ct} users with duplicate emails')
        users_valid_names = users_unique_emails.filter(~Q(first_name='') & ~Q(last_name=''))
        invalid_name_ct = users_unique_emails.count() - users_valid_names.count()
        logger.info(f'[ch14855] filtered {invalid_name_ct} users with invalid names')
        all_profiles = UserProfile.objects.all()
        valid_profiles = all_profiles.filter(user__in=users_valid_names)
        no_profile_ct = users_valid_names.count() - all_profiles.count()
        logger.info(f'[ch15689] filtered {no_profile_ct} users without profiles')
        return valid_profiles


class UserProfileManager(models.Manager.from_queryset(UserProfileQuerySet)):
    pass


class UserProfile(models.Model):
    """
    UserProfile keeps a timestamp of the disclaimers signed by user. It also can act as a temp
    directory to save per user searches and filters
    """

    class Role:
        MASTER_ADMIN = 'master_admin'
        ADMIN = 'admin'
        STAFF = 'staff'
        JUNIOR_STAFF = 'junior_staff'

        CHOICES = (
            (MASTER_ADMIN, 'Master Admin'),
            (ADMIN, 'Admin'),
            (STAFF, 'Staff'),
            (JUNIOR_STAFF, 'Junior Staff'),
        )

    company = models.ForeignKey('Company', null=True, blank=True, on_delete=models.CASCADE)
    user = models.OneToOneField(User, related_name="profile", on_delete=models.CASCADE)
    phone = models.CharField(null=True, max_length=255)
    role = models.CharField(max_length=16, default='staff', choices=Role.CHOICES)
    unread_prospect_count = models.PositiveIntegerField(default=0)

    # Each company can have 1 primary user, which is used for contacting for account-owner topics.
    is_primary = models.BooleanField(default=False)

    # Data about the user agreeing to the user agreement
    disclaimer_signature = models.CharField(max_length=255, null=True, blank=True)
    disclaimer_timestamp = models.DateTimeField(null=True, blank=True)

    # Employee start time. If null, default to the company's time.
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    # If the user registered using landing page, they may have an invite code.
    invite_code = models.CharField(max_length=32, null=True, blank=True)

    interesting_features = models.ManyToManyField('sherpa.Features')

    objects = UserProfileManager()

    @cached_property
    def unread_prospects(self):
        """
        Returns a queryset of `Prospect` that are unread for a given user, based on their campaign
        permissions.
        """
        from sherpa.models import Prospect
        if not self.company:
            return Prospect.objects.none()

        prospect_set = self.company.prospect_set.filter(has_unread_sms=True)

        # For non-admins, we'll want to return the campaign prospects too in prefetch.
        if not self.is_admin:
            prospect_set.prefetch_related('campaignprospect_set')

        return prospect_set

    @property
    def unread_prospect_count_calculated(self):
        """
        Return an integer of the distinct prospect count that have an unread message.

        We moved away from using a live query due to performance reasons, and instead are using an
        aggregated field. This method might end up not being used in the code, but can be used for
        manual checks on the actual data and finding how many unread messages the user should have.
        """
        from sherpa.models import Campaign, CampaignProspect
        access_campaigns = Campaign.objects.has_access(self.user).filter(
            has_unread_sms=True,
        ).values_list('id', flat=True)
        unread_prospects = self.unread_prospects
        access_unread_count = CampaignProspect.objects.filter(
            campaign_id__in=access_campaigns,
            prospect__id__in=unread_prospects.values_list('id', flat=True),
        ).values('prospect').distinct().count()
        return access_unread_count

    @property
    def can_skiptrace(self):
        """
        Determines if the company has permission to create skip traces.
        """
        if not self.company.is_demo:
            return True

        # Only allow demo companies to upload two skip trace instances.
        return self.user.uploadskiptrace_set.exclude(
            status=UploadSkipTrace.Status.SETUP,
        ).count() < 2

    @property
    def has_latest_agreement(self):
        """
        Check if the user has signed the latest agreement.

        In the future when we update the user agreement, all we'll need to do is set this date to be
        a cutoff date after the registration implementation and then they'll need to agree again to
        the user agreement.
        """
        # Set the latest agreement date and prompt users to agree if they have a timestamp previous.
        latest_agreement_date = date(2020, 3, 18)
        timestamp = self.disclaimer_timestamp
        return timestamp and timestamp.date() >= latest_agreement_date

    @property
    def fullname(self):
        return self.user.get_full_name()

    @property
    def prospect_relay_count(self):
        return self.prospectrelay_set.count()

    @property
    def is_master_admin(self):
        return self.role == 'master_admin'

    @property
    def is_admin(self):
        return self.is_master_admin or self.role == 'admin'

    @property
    def is_staff(self):
        return self.is_admin or self.role == 'staff'

    @property
    def is_junior_staff(self):
        return self.is_staff or self.role == 'junior_staff'

    @property
    def employee_start_time(self):
        return self.start_time or self.company.start_time

    @property
    def employee_end_time(self):
        return self.end_time or self.company.end_time

    @property
    def phone_display(self):
        if self.phone is None:
            return ""
        if len(self.phone) == 10:
            return "(%s) %s-%s" % (self.phone[:3], self.phone[3:6], self.phone[6:])
        else:
            return ""

    @property
    def disclaimer_timestamp_local(self):
        try:
            if self.company.timezone:
                tz = self.company.timezone
                local_tz = pytz.timezone(tz)
            else:
                local_tz = pytz.timezone('US/Mountain')
        except Exception:
            local_tz = pytz.timezone('US/Mountain')

        if self.disclaimer_timestamp:
            local_dt = self.disclaimer_timestamp.replace(tzinfo=pytz.utc).astimezone(local_tz)
            year_string = local_dt.year
            month_string = local_dt.month
            day_string = local_dt.day
            military_time_hours = local_dt.hour
            time_minutes_formatted = local_dt.minute
            datetime_now_local = datetime.strptime(
                "%s-%s-%s %s:%s:00" % (
                    year_string,
                    month_string,
                    day_string,
                    military_time_hours,
                    time_minutes_formatted,
                ),
                "%Y-%m-%d %H:%M:%S")

            return datetime_now_local
        else:
            return ''

    @property
    def prospect_relay_available(self):
        total_active_sms_relay_numbers = settings.TELNYX_RELAY_CONNECTIONS
        total_available = total_active_sms_relay_numbers - self.prospect_relay_count
        return total_available

    @property
    def created_timestamp(self):
        """
        Unix timestamp of when user was created.
        """
        return self.user.date_joined.strftime('%s')

    @property
    def feature_notifications(self):
        return UserFeatureNotification.objects.filter(user_profile=self)

    def send_stats(self, start_date=None, end_date=None):
        """
        Return the sending and lead stats for the user.
        """
        from sherpa.models import Prospect, SMSMessage
        user = self.user
        date_kwargs = {}
        qualified_kwargs = {}
        tz = pytz.timezone(self.company.timezone)

        start_time = self.employee_start_time
        end_time = self.employee_end_time

        # If no start or end dates were sent, default to past day only.
        if not start_date:
            start_date = datetime.now().date() - timedelta(days=1)
        if not end_date:
            end_date = datetime.now().date()

        # Convert the start_date and end_date into the datetime for for the company's timezone.
        start_datetime = datetime.combine(start_date, datetime.min.time())
        day_tz_start = tz.localize(start_datetime)
        date_kwargs['dt__gte'] = day_tz_start
        qualified_kwargs['qualified_lead_dt__gte'] = day_tz_start

        # Get the start time for the business hours
        business_start = tz.localize(start_datetime).replace(
            hour=start_time.hour,
            minute=start_time.minute,
        )
        business_time_start = business_start.astimezone(pytz.utc).time()

        # Get the start/end datetimes for the company timezone.
        end_datetime = datetime.combine(end_date, datetime.max.time())
        day_tz_end = tz.localize(end_datetime)
        date_kwargs['dt__lte'] = day_tz_end
        qualified_kwargs['qualified_lead_dt__lte'] = day_tz_end

        # Get the start/end datetimes for the business hours
        business_datetime_end = tz.localize(end_datetime).replace(
            hour=end_time.hour,
            minute=end_time.minute,
            second=0,
            microsecond=0,
        )
        business_time_end = business_datetime_end.astimezone(pytz.utc).time()

        # Go through and get all of our stats to return.
        attempts_count = SMSMessage.objects.filter(
            initial_message_sent_by_rep=user,
            **date_kwargs,
        ).count()

        delivered_count = SMSMessage.objects.filter(
            initial_message_sent_by_rep=user,
            message_status='delivered',
            **date_kwargs,
        ).count()

        qualified_lead_count = Prospect.objects.filter(
            qualified_lead_created_by=user,
            **qualified_kwargs,
        ).count()

        # For response time, replace the start/end time with the timezone 9am-6pm.
        response_time_seconds_dict = SMSMessage.objects.filter(
            response_from_rep=user,
        ).annotate(
            # Perhaps these should be fields on the model itself?
            msg_date=TruncDate('dt', output_field=models.DateField()),
            msg_time=TruncTime('dt', output_field=models.TimeField()),
        ).filter(msg_date__range=(start_date, end_date))

        if business_time_end > business_time_start:
            response_time_seconds_dict = response_time_seconds_dict.filter(
                msg_time__range=(business_time_start, business_time_end),
            )
        else:
            # The end time has rolled over to next day due to UTC conversion.
            ending = Q(msg_time__range=(time(0, 0), business_time_end))
            starting = Q(msg_time__range=(business_time_start, time(23, 59, 59, 999999)))
            response_time_seconds_dict = response_time_seconds_dict.filter(ending | starting)

        response_time_seconds_dict = response_time_seconds_dict.aggregate(
            Avg('response_time_seconds'),
        )

        avg_response_time_seconds = response_time_seconds_dict.get(
            "response_time_seconds__avg") or 0
        lead_rate = round(qualified_lead_count / delivered_count * 100) if delivered_count else 0

        return {
            "attempts": attempts_count,
            "delivered": delivered_count,
            "leads_created": qualified_lead_count,
            "lead_rate": lead_rate,
            "avg_response_time": math.ceil(avg_response_time_seconds / 60),
        }

    def update_agreement(self):
        """
        Update the data associated with the user signing the agreement.
        """
        self.disclaimer_timestamp = django_tz.now()
        self.disclaimer_signature = self.user.get_full_name()
        self.save(update_fields=['disclaimer_timestamp', 'disclaimer_signature'])

    def admin_switch_company(self, company):
        """
        Sets the user profile company field to company.

        Only Sherpa staff should use this feature.
        """
        self.company = company
        self.save(update_fields=['company'])

    def __str__(self):
        return self.user.username

    def save(self, *args, **kwargs):
        """
        Don't allow multiple primary accounts for a company.
        """
        company = self.company
        if self.is_primary and company and company.admin_profile and self != company.admin_profile:
            raise ValidationError(f"Can't save multiple primary profiles for {self.company.name}.")
        super(UserProfile, self).save(*args, **kwargs)

    class Meta:
        app_label = 'sherpa'


class UserFeatureNotification(models.Model):
    """
    Generic feature notifications for each user.
    """
    user_profile = models.ForeignKey(UserProfile, null=True, blank=True, on_delete=models.CASCADE)
    feature_notification = models.ForeignKey(
        FeatureNotification, null=True, blank=True, on_delete=models.CASCADE)
    is_dismissed = models.BooleanField(default=False)
    is_tried = models.BooleanField(default=False)
    dismissed_or_tried_dt = models.DateTimeField(null=True, blank=True)
    display_count = models.IntegerField(default=0)

    @property
    def display_feature(self):
        if self.display_count <= self.feature_notification.display_amount and not self.is_tried:
            return True
        return False

    class Meta:
        app_label = 'sherpa'
        unique_together = ('user_profile', 'feature_notification')

    def __str__(self):
        return self.user_profile.user.username


@receiver(post_save, sender=User)
def create_profile(sender, instance, signal, *args, **kwargs):
    """
    Create UserProfile we User is created generated token.
    """
    if kwargs.get('raw', False):
        # Don't run when loading fixtures
        return False

    profile, new = UserProfile.objects.get_or_create(user=instance)
    if new:
        profile.role = UserProfile.Role.MASTER_ADMIN
        profile.save()
    return profile
