from django.utils import timezone as django_tz

from accounts.models.company import Company
from core import models

__all__ = (
    'RoiStat',
)


class RoiStat(models.Model):
    """
    Used in private dashboard for Jason to track profit on each company.
    """
    BRAINTREE_FIXED_FEE = 0.2
    BRAINTREE_PERCENT_FEE = 0.022
    TWILIO_MESSAGE_FEE = 0.00488
    SKIP_TRACE_FEE = 0.08

    company = models.ForeignKey(Company, on_delete=models.CASCADE)
    period_start = models.DateTimeField()
    period_end = models.DateTimeField()
    company_pays_own_twilio = models.BooleanField(default=False)

    revenue_subscription = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    revenue_subscription_count = models.IntegerField(default=0)
    revenue_skip_trace = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    revenue_skip_trace_count = models.IntegerField(default=0)
    revenue_additional_uploads = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    revenue_additional_uploads_count = models.IntegerField(default=0)
    revenue_other = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    revenue_other_count = models.IntegerField(default=0)

    count_sms_sent = models.IntegerField(default=0)
    count_sms_received = models.IntegerField(default=0)
    count_phone_numbers = models.IntegerField(default=0)
    count_prospects = models.IntegerField(default=0)
    count_unique_prospects = models.IntegerField(default=0)
    count_phone_type_lookup = models.IntegerField(default=0)
    count_skip_trace_hits = models.IntegerField(default=0)
    count_skip_trace_uploads = models.IntegerField(default=0)

    subscription_signup_date = models.DateTimeField(null=True, blank=True)
    next_billing_date = models.DateField(null=True, blank=True)

    @property
    def total_lead_sherpa_revenue(self):
        return self.revenue_subscription + self.revenue_additional_uploads + self.revenue_other

    @property
    def expense_sms_sent(self):
        return float(self.count_sms_sent) * self.TWILIO_MESSAGE_FEE

    @property
    def expense_sms_received(self):
        return float(self.count_sms_received) * self.TWILIO_MESSAGE_FEE

    @property
    def expense_phone_lookup(self):
        # discount with twilio from .0045 to .00325
        return float(self.count_phone_type_lookup) * .00325

    @property
    def expense_phone_numbers(self):
        # discount with twilio from .85 to .5
        return float(self.count_phone_numbers) * .5

    @property
    def expense_braintree_leadsherpa(self):
        total_transactions = self.revenue_subscription_count + \
            self.revenue_additional_uploads_count + \
            self.revenue_other_count
        per_transaction_fee = float(total_transactions) * self.BRAINTREE_FIXED_FEE
        percentage_fee = float(self.total_lead_sherpa_revenue) * self.BRAINTREE_PERCENT_FEE
        return per_transaction_fee + percentage_fee

    @property
    def expense_braintree_skip_trace(self):
        total_transactions = self.revenue_skip_trace_count
        per_transaction_fee = float(total_transactions) * self.BRAINTREE_FIXED_FEE
        percentage_fee = float(self.revenue_skip_trace) * self.BRAINTREE_PERCENT_FEE
        return per_transaction_fee + percentage_fee

    @property
    def expense_skip_trace(self):
        return float(self.count_skip_trace_hits) * self.SKIP_TRACE_FEE

    @property
    def expense_skip_trace_plus_braintree(self):
        """
        Include total expense of skip trace with its braintree transaction fees.
        """
        expense_skip_trace = float(self.count_skip_trace_hits) * self.SKIP_TRACE_FEE
        expense_braintree_skip_trace = float(self.expense_braintree_skip_trace)

        return expense_skip_trace + expense_braintree_skip_trace

    @property
    def profit_skip_trace(self):
        try:
            return float(self.revenue_skip_trace) - float(self.expense_skip_trace_plus_braintree)
        except Exception:
            return 0

    @property
    def profit_margin_skip_trace(self):
        try:
            gross_profit = float(self.revenue_skip_trace) - float(
                self.expense_skip_trace_plus_braintree)
            margin = gross_profit / float(self.revenue_skip_trace)
            margin_percentage = float(margin) * 100
            return margin_percentage
        except ZeroDivisionError:
            return None

    @property
    def total_lead_sherpa_expense(self):
        return self.expense_sms_sent + \
            self.expense_sms_received + \
            self.expense_phone_lookup + \
            self.expense_phone_numbers + \
            self.expense_braintree_leadsherpa

    @property
    def profit_margin_lead_sherpa(self):
        try:
            gross_profit = float(self.total_lead_sherpa_revenue) - \
                float(self.total_lead_sherpa_expense)
            margin = gross_profit / float(self.total_lead_sherpa_revenue)
            margin_percentage = float(margin) * 100
            return margin_percentage
        except ZeroDivisionError:
            return None

    @property
    def days_since_subscription_signup(self):
        now = django_tz.now()
        signup_date = self.subscription_signup_date

        days = now.date() - signup_date.date()
        return days.days
