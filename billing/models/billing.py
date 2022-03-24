from datetime import datetime
from decimal import Decimal

import pytz

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import EmailMultiAlternatives
from django.db.models import Q
from django.template.loader import render_to_string
from django.utils import timezone as django_tz

from accounts.models.company import Company
from billing.models import product
from companies.managers import InvitationCodeManager
from core import models
from skiptrace import SKIP_TRACE_DEFAULT_PRICE

__all__ = (
    'InvitationCode', 'SubscriptionCancellationRequest',
)

User = get_user_model()


class InvitationCode(models.Model):
    """
    Allows access and sets up Sherpa subscription when a user first signs up.

    Affiliate's a unique/special type of invitation code which offered 2 pricing tiers to choose
    from.
    """
    code = models.CharField(blank=True, max_length=32, unique=True)
    is_active = models.BooleanField(default=True)
    discount_code = models.CharField(max_length=32, blank=True)
    description = models.CharField(max_length=128, blank=True)
    is_skip_trace_invitation = models.BooleanField(default=False)
    allow_starter = models.BooleanField(default=False)
    skip_trace_price = models.DecimalField(
        default=SKIP_TRACE_DEFAULT_PRICE,
        decimal_places=2,
        max_digits=3,
    )

    objects = InvitationCodeManager()

    def __str__(self):
        return self.code

    class Meta:
        app_label = 'sherpa'

    @property
    def discount_amount(self):
        """
        Returns a decimal amount of the discount that should be applied on the invation code.
        """
        from billing.models import Gateway

        if not self.discount_code:
            return Decimal('0.00')

        all_discounts = Gateway.discount.all()
        for discount in all_discounts:
            if discount.id == self.discount_code:
                return discount.amount

        return Decimal('0.00')

    @property
    def active_subscribers(self):
        return self.company_set.filter(
            ~Q(subscription_id=''),
            subscription_status__in=[
                Company.SubscriptionStatus.ACTIVE,
                Company.SubscriptionStatus.PAST_DUE,
            ],
        )

    @property
    def active_users(self):
        return self.company_set.all()

    @property  # noqa: C901
    def last_signup_date(self):
        """
        Companies can sign up multiple times (for unknown reasons), sometimes they'll have a
        skiptrace signup and then a subscription signup.

        This is only used in the invitation code count page, and would be nice to cleanup.
        """
        if self.code == 'skipsherpa':
            company_list = Company.objects.filter(
                Q(status='active'), Q(invitation_code=self)).order_by('-subscription_signup_date')
            if len(company_list) > 0:
                company = company_list[0]

                try:
                    if company.timezone:
                        tz = company.timezone
                        local_tz = pytz.timezone(tz)
                    else:
                        local_tz = pytz.timezone('US/Mountain')
                except Exception:
                    local_tz = pytz.timezone('US/Mountain')

                if company.subscription_signup_date:
                    local_dt = company.subscription_signup_date.replace(
                        tzinfo=pytz.utc).astimezone(local_tz)
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

                return ''
            else:
                return ''

        company_list = Company.objects.filter(
            Q(invitation_code=self),
            (Q(subscription_status='active') | Q(subscription_status='Active')),
        ).order_by('-subscription_signup_date')

        if len(company_list) > 0:
            company = company_list[0]

            try:
                if company.timezone:
                    tz = company.timezone
                    local_tz = pytz.timezone(tz)
                else:
                    local_tz = pytz.timezone('US/Mountain')
            except Exception:
                local_tz = pytz.timezone('US/Mountain')

            if company.subscription_signup_date:
                local_dt = company.subscription_signup_date.replace(
                    tzinfo=pytz.utc).astimezone(local_tz)
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

        return ''


class SubscriptionCancellationRequest(models.Model):
    """
    Used when a Company requests a Sherpa subscription cancellation. The nightly job picks up these
    requests and processes them.
    """

    class Status:
        PENDING = 'pending'  # When a request is filed not but accepted yet
        ACCEPTED_PENDING = 'accepted_pending'  # A request is scheduled for cancellation
        COMPLETE = 'accepted_complete'  # A user's account has been cancelled.
        SAVED = 'saved'
        REJECTED = 'rejected'

        CHOICES = (
            (PENDING, 'Pending'),
            (ACCEPTED_PENDING, 'Accepted Pending'),
            (SAVED, 'Saved'),
            (REJECTED, 'Rejected'),
            (COMPLETE, 'Complete'),
        )

    class Reason:
        NO_LEADS = 'no_leads'
        MISSING_FUNC = 'missing_functionality'
        PRICING = 'pricing'
        NOT_USING = 'not_using'
        COMPETITOR = 'competitor'
        PAUSE = 'pause'
        OTHER = 'other'

        CHOICES = (
            (NO_LEADS, 'No Leads'),
            (MISSING_FUNC, 'Missing Functionality'),
            (PRICING, 'Pricing to High'),
            (NOT_USING, 'Not Using'),
            (COMPETITOR, 'Moving to Competitor'),
            (PAUSE, 'Pause'),
            (OTHER, 'Other'),
        )

    company = models.ForeignKey(
        Company, related_name='cancellation_requests', on_delete=models.CASCADE)
    requested_by = models.ForeignKey(User, on_delete=models.CASCADE)
    request_datetime = models.DateTimeField(auto_now_add=True)
    cancellation_reason_text = models.CharField(max_length=256, blank=True)
    cancellation_reason = models.CharField(max_length=32, choices=Reason.CHOICES)
    status = models.CharField(max_length=17, default=Status.PENDING, choices=Status.CHOICES)

    # Cancellation date is when the user's current billing cycle ends.
    # TODO: (AWW20190822) cancellation date is stored in both company and here, need to remove from
    # company.
    cancellation_date = models.DateField(null=True, blank=True)

    # Requests
    discount = models.BooleanField(
        default=False, help_text="Requests the cancellation discount on their next billing cycle.")
    pause = models.BooleanField(default=False, help_text="Request that the account be paused.")
    new_plan = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="The new plan ID that company wishes to downgrade to.",
    )

    class Meta:
        app_label = 'sherpa'

    @property
    def request_datetime_local(self):
        try:
            if self.company.timezone:
                tz = self.company.timezone
                local_tz = pytz.timezone(tz)
            else:
                local_tz = pytz.timezone('US/Mountain')
        except Exception:
            local_tz = pytz.timezone('US/Mountain')

        if self.request_datetime:
            local_dt = self.request_datetime.replace(tzinfo=pytz.utc).astimezone(local_tz)
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

    def fulfill(self):
        """
        Method to cancel a company's subscription.

        Usually we'll bulk cancel through logic in command `cancel_sherpa_account`, however we can
        also fulfill a single instance with this method.

        TODO: (aww20190903) Should not require cancellation request to cancel a company's
        subscription. This should be available from a company instance.
        """
        from billing.models import Gateway
        from phone.tasks import deactivate_company_markets

        company = self.company
        subscription_id = company.subscription_id

        # Clear subscription_id so user still has access to skip trace.
        company.subscription_status = 'canceled'
        company.subscription_id = ''
        company.has_cancellation_request = False
        company.cancellation_date = None
        company.save(update_fields=[
            'subscription_status',
            'subscription_id',
            'has_cancellation_request',
            'cancellation_date',
        ])

        self.status = 'accepted_complete'
        self.save(update_fields=['status'])

        # Call task and release sherpa phone numbers.
        deactivate_company_markets.delay(company.id)

        # Update skip trace price from .12 to default
        company.skip_trace_price = SKIP_TRACE_DEFAULT_PRICE
        company.save(update_fields=['skip_trace_price'])

        # Cancel braintree subscription.
        try:
            # TODO: (awwester20190826) for some reason we can't find subsriptions.
            Gateway.subscription.cancel(subscription_id)
        except Exception:
            pass

        # Send notification email to the requestor.
        cc_email = "support@leadsherpa.com"
        from_email = settings.DEFAULT_FROM_EMAIL
        subject = 'Subscription Canceled - {} - {}'.format(company.name, company.admin_name)
        to = self.requested_by.email
        text_content = 'Account Cancellation Complete'
        html_content = render_to_string('email/email_subscription_cancellation_confirmation.html')

        email = EmailMultiAlternatives(subject, text_content, from_email, [to], cc=[cc_email])
        email.attach_alternative(html_content, "text/html")
        email.send()

    def handle_pause(self):
        """
        Handles the pause cancellation flow.
        """
        if not self.pause or self.company.has_annual_subscription:
            return {}

        data = {}
        company = self.company
        pause_check = [
            company.subscription_status != Company.SubscriptionStatus.PAUSED,
            not company.awaiting_subscription_pause(cancellation_request=self),
        ]

        if not all(pause_check):
            #  Requesting to pause the account but already done.
            raise Exception("Company already paused.")

        #  Pausing an account will happen on the night of their next billing date.
        pause_price = self.company.pause_price
        self.company.set_pause_subscription_price(pause_price)
        data["subscription_price"] = pause_price
        data["last_billing_date"] = self.company.next_billing_date or django_tz.now().date()

        self.status = SubscriptionCancellationRequest.Status.ACCEPTED_PENDING
        self.save(update_fields=['status'])

        return data

    def handle_discount(self):
        """
        Handles the discount cancellation flow.
        """
        if not self.discount or self.company.has_annual_subscription:
            return {}

        data = {}
        company = self.company
        discount_check = [
            not company.cancellation_discount,
            not company.cancellation_discount_dt,
            company.subscription_status != Company.SubscriptionStatus.PAUSED,
            not company.awaiting_subscription_pause(cancellation_request=self),
        ]
        if not all(discount_check):
            error_check = [
                company.awaiting_subscription_pause(cancellation_request=self),
                company.subscription_status == Company.SubscriptionStatus.PAUSED,
            ]
            if any(error_check):
                #  Do not allow a paused company to apply the half off discount.
                raise Exception("Cannot apply discount to a paused company.")
            raise Exception("Discount already applied.")

        data["subscription_price"] = company.apply_cancellation_discount_to_subscription()
        data["discount_applied"] = True

        company.cancellation_discount = True
        company.cancellation_discount_dt = django_tz.now()
        company.save(update_fields=['cancellation_discount', 'cancellation_discount_dt'])

        self.status = SubscriptionCancellationRequest.Status.SAVED
        self.save(update_fields=['status'])

        return data

    def handle_downgrade(self):
        """
        Handles the downgrade cancellation flow.
        """
        if not self.new_plan or self.company.has_annual_subscription:
            return {}

        data = {}
        plan = self.company.plan
        downgrade_opts = {
            product.SMS_SH2000: product.SMS_PRO,
            product.SMS_ENTERPRISE: product.SMS_PRO,
            product.SMS_PRO: product.SMS_CORE,
            product.SMS_CORE: product.SMS_STARTER,
        }
        new_plan_check = [
            self.new_plan,
            any([
                plan['id'] == product_code and self.new_plan == downgrade_opts[product_code]
                for product_code in downgrade_opts.keys()
            ]),
        ]
        if not all(new_plan_check):
            raise Exception(
                f"{plan['id']} subscriptions can only downgrade to {downgrade_opts[plan['id']]}.")

        data["subscription_price"] = self.company.switch_subscription(self.new_plan)

        self.status = SubscriptionCancellationRequest.Status.SAVED
        self.save(update_fields=['status'])

        return data
