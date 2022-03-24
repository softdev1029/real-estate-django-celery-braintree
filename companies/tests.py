from datetime import date, timedelta
import os

from model_mommy import mommy

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from billing.models import product
from campaigns.models import CampaignDailyStats
from campaigns.tests import CampaignDataMixin
from services.crm.podio import podio
from sherpa.models import (
    Company,
    InternalDNC,
    InvitationCode,
    PhoneNumber,
    Prospect,
    SubscriptionCancellationRequest,
)
from sherpa.tests import (
    AdminUserMixin,
    AllUserRoleMixin,
    BaseAPITestCase,
    CompanyOneMixin,
    CompanyTwoMixin,
    NoDataBaseTestCase,
)
from sms.models import CarrierApprovedTemplate
from .models import CompanyPodioCrm, TelephonyConnection
from .tasks import process_cancellation_requests

User = get_user_model()


class CompanyAPITestCase(AllUserRoleMixin, CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):
    me_url = reverse('user-me')

    def setUp(self):
        super(CompanyAPITestCase, self).setUp()
        detail_kwargs = {'pk': self.company1.pk}
        self.company_detail_url = reverse('company-detail', kwargs=detail_kwargs)
        self.transactions_url = reverse('company-transactions', kwargs=detail_kwargs)
        self.subscription_url = reverse('company-subscription', kwargs=detail_kwargs)
        self.purchase_credits_url = reverse('company-purchase-credits', kwargs=detail_kwargs)
        self.uploads_remaining_url = reverse('company-uploads-remaining', kwargs=detail_kwargs)
        self.retry_subscription = reverse('company-retry-subscription', kwargs=detail_kwargs)
        self.set_invitation_code_url = reverse('company-invitation-code', kwargs=detail_kwargs)

        self.new_user = mommy.make(
            User,
            first_name="New",
            last_name="User",
            username="new.user@asdf.com",
            email="new.user@asdf.com",
            is_active=True,
        )
        profile = self.new_user.profile
        profile.phone = '555-555-5555'
        profile.save(update_fields=['phone'])
        self.new_client = APIClient()
        self.new_client.force_authenticate(user=self.new_user)

    def test_anonymous_cant_get_company(self):
        response = self.client.get(self.company_detail_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_their_company(self):
        response = self.master_admin_client.get(self.company_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.company1.id)
        self.assertEqual(response.json().get('name'), self.company1.name)

    def test_user_company_shows_user_profiles(self):
        response = self.master_admin_client.get(self.company_detail_url)
        self.assertEqual(response.status_code, 200)
        profiles = response.json().get('profiles')
        self.assertNotEqual(profiles, None)

        for profile_data in profiles:
            user = User.objects.get(id=profile_data.get('id'))
            self.assertEqual(profile_data.get('user').get('id'), user.id)

    def test_user_cant_get_others_company(self):
        response = self.company2_client.get(self.company_detail_url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_user_can_set_their_default_alternate_message(self):
        data = {'default_alternate_message': 'test message {CompanyName}'}
        response = self.master_admin_client.patch(self.company_detail_url, data)
        self.assertEqual(response.status_code, 200)
        self.company1.refresh_from_db()

    def test_user_cannot_set_default_alternate_message_with_brackets(self):
        data = {'default_alternate_message': 'test message {TestMessage}'}
        response = self.master_admin_client.patch(self.company_detail_url, data)
        self.assertEqual(response.status_code, 400)

    def test_user_cant_set_others_default_alternate_message(self):
        data = {'default_alternate_message': 'test message'}
        response = self.company2_client.patch(self.company_detail_url, data)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_user_can_copy_their_default_alternate_message(self):
        new_alternate = 'test message {CompanyName}'
        data = {'default_alternate_message': new_alternate}
        self.master_admin_client.patch(self.company_detail_url, data)

        template = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message='Hello {FirstName}',
            alternate_message='This is the alternative.',
        )

        response = self.master_admin_client.post(
            self.company_detail_url + 'copy_alternate_message/')
        self.assertEqual(response.status_code, 200)
        template.refresh_from_db()
        self.assertEqual(template.alternate_message, new_alternate)

    def test_cant_purchase_credits_without_authentication(self):
        payload = {'amount': 40}
        response = self.client.post(self.purchase_credits_url, payload)
        self.assertEqual(response.status_code, 401)

    def test_purchase_credits_returns_error_when_no_amount(self):
        response = self.master_admin_client.post(self.purchase_credits_url, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('detail'), 'Must include amount.')

    def test_new_user_can_register_company(self):
        url = reverse('company-list')

        features = ['skip_trace', 'direct_mail']
        payload = {
            'name': 'New Company, LLC',
            'real_estate_experience_rating': 4,
            'billing_address': '840  Atha Drive',
            'city': 'Bakersfield',
            'state': 'CA',
            'zip_code': '93301',
            'timezone': 'US/Pacific',
            'interesting_features': features,
        }

        response = self.new_client.post(url, payload)
        self.assertEqual(response.status_code, 201)
        pk = response.json().get('id')
        company = Company.objects.get(pk=pk)
        self.assertEqual(
            company.real_estate_experience_rating,
            payload['real_estate_experience_rating'],
        )
        self.assertEqual(company.name, payload['name'])
        self.new_user.refresh_from_db()
        self.assertEqual(self.new_user.profile.company.pk, company.pk)
        self.assertTrue(self.new_user.profile.disclaimer_timestamp is not None)
        self.assertEqual(self.new_user.profile.interesting_features.count(), len(features))

    def test_new_user_can_register_company_with_code(self):
        url = reverse('company-list')
        payload = {
            'name': 'New Company, LLC',
            'real_estate_experience_rating': 4,
            'billing_address': '840  Atha Drive',
            'city': 'Bakersfield',
            'state': 'CA',
            'zip_code': '93301',
            'invitation_code': 'BAD-CODE',
        }

        response = self.new_client.post(url, payload)
        self.assertEqual(response.status_code, 400)

        payload['invitation_code'] = 'code1'
        response = self.new_client.post(url, payload)
        self.assertEqual(response.status_code, 201)

    def test_purchase_credits_returns_error_when_amount_below_minimum(self):
        payload = {'amount': settings.MIN_CREDIT - 1}
        response = self.master_admin_client.post(self.purchase_credits_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get('detail'),
            f'Amount is less than minimum. Must be at least {settings.MIN_CREDIT} credits.',
        )

    def test_can_purchase_skip_trace_credits(self):
        payload = {'amount': settings.MIN_CREDIT}
        response = self.master_admin_client.post(self.purchase_credits_url, payload)
        self.master_admin_user.profile.company.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.master_admin_user.profile.company.sherpa_balance, settings.MIN_CREDIT)

    def test_can_toggle_auto_dead(self):
        # Verify can enable auto dead
        self.assertIsNone(self.company1.auto_dead_enabled)
        payload = {'autoDeadEnabled': True}
        response = self.master_admin_client.patch(self.company_detail_url, payload)
        self.company1.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.company1.auto_dead_enabled, True)

        # Verify can disable auto dead
        payload = {'autoDeadEnabled': False}
        response = self.master_admin_client.patch(self.company_detail_url, payload)
        self.company1.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.company1.auto_dead_enabled, False)

    def test_total_skip_trace_savings(self):
        # Verify total savings is returned as zero if there's no skip traces
        url = self.me_url
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('company').get('totalSkipTraceSavings'), 0)

        # Verify total savings is zero if there's a skip trace with no existing matches
        skip_trace1 = mommy.make(
            'sherpa.UploadSkipTrace',
            company=self.company1,
            total_existing_matches=0,
        )
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('company').get('totalSkipTraceSavings'), 0)

        # Verify that savings are calculated as total existing matches * skip trace price.
        self.company1.skip_trace_price = .1
        self.company1.save(update_fields=['skip_trace_price'])
        skip_trace1.total_existing_matches = 10
        skip_trace1.save(update_fields=['total_existing_matches'])
        mommy.make('sherpa.UploadSkipTrace', company=self.company1, total_existing_matches=5)
        response = self.master_admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('company').get('totalSkipTraceSavings'), 1.5)

    def test_can_get_profile_stats(self):
        url = reverse('company-profile-stats', kwargs={'pk': self.company1.id})

        # Verify without any date filters.
        response = self.jrstaff_client.get(url)
        self.assertEqual(response.status_code, 200)

        # Verify with start and end date filters.
        response = self.jrstaff_client.get(url + '?start_date=2020-01-01&end_date=2020-05-01')
        self.assertEqual(response.status_code, 200)

    def test_staff_cant_get_transactions(self):
        response = self.staff_client.get(self.transactions_url)
        self.assertEqual(response.status_code, 403)

    def test_cant_get_others_transactions(self):
        response = self.company2_client.get(self.transactions_url)
        self.assertEqual(response.status_code, 404)

    def test_staff_cant_get_subscription(self):
        response = self.staff_client.get(self.subscription_url)
        self.assertEqual(response.status_code, 403)

    def test_cant_get_others_subscription(self):
        response = self.company2_client.get(self.subscription_url)
        self.assertEqual(response.status_code, 404)

    def test_skip_trace_can_get_subscription(self):
        self.company1.subscription_id = ''
        self.company1.save()
        response = self.admin_client.get(self.subscription_url)
        self.assertEqual(response.status_code, 200)

    def test_cant_register_invalid_subscription_plan(self):
        invalid = 'asdf'
        self.company1.subscription_id = ''
        self.company1.save()
        response = self.master_admin_client.post(self.subscription_url, {
            'plan_id': invalid,
            'annual': False,
        })
        self.assertEqual(response.status_code, 400)

    def test_cant_create_annual_starter(self):
        self.company1.subscription_id = ''
        self.company1.save()
        response = self.master_admin_client.post(self.subscription_url, {
            'plan_id': product.SMS_STARTER,
            'annual': True,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json().get('detail'),
            'Could not process annual subscription for plan starter',
        )

    def test_can_get_company_uploads_remaining_data(self):
        response = self.master_admin_client.get(self.uploads_remaining_url)
        self.assertEqual(response.status_code, 200)

    def test_retry_subscription(self):
        # Not testing too much, but we need to have an actual past due balance in braintree.
        response = self.admin_client.post(self.retry_subscription)
        self.assertEqual(response.status_code, 200)

    def test_set_invitation_code(self):
        # First test an invalid invitation code.
        payload = {'code': 'invalid'}
        invalid_response = self.admin_client.post(self.set_invitation_code_url, payload)
        self.assertEqual(invalid_response.status_code, 400)
        self.assertNotEqual(invalid_response.json().get('detail'), None)

        # Now let's test setting a valid invitation code
        invitation_code = InvitationCode.objects.first()
        payload = {'code': invitation_code.code}
        valid_response = self.admin_client.post(self.set_invitation_code_url, payload)
        self.assertEqual(valid_response.status_code, 200)
        self.assertEqual(
            valid_response.json().get('invitationCode').get('id'), invitation_code.id)
        self.company1.refresh_from_db()
        self.assertEqual(self.company1.invitation_code, invitation_code)

    def test_can_get_company_prospect_count(self):
        url = reverse('company-prospect-count', kwargs={'pk': self.company1.pk})
        response = self.admin_client.get(url)
        self.assertEqual(response.json().get('count'), self.company1.prospect_set.count())

    def test_subscribe_templates(self):
        template = mommy.make(
            'sms.CarrierApprovedTemplate',
            message='first',
            alternate_message='first',
            is_active=True,
            is_verified=True,
        )
        template2 = mommy.make(
            'sms.CarrierApprovedTemplate',
            message='second',  # noqa: E501
            alternate_message='second',
            is_active=True,
            is_verified=True,
        )
        url = reverse('company-templates', kwargs={'pk': self.company1.pk})
        payload = {
            'templates': [template.id, template2.id],
        }

        #  Test setting templates.
        response = self.admin_client.post(url, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get('templates'), [template.id, template2.id])

        #  Test not sending enough templates, results in 400.
        payload = {
            'templates': [template.id],
        }
        response = self.admin_client.post(url, payload)
        self.assertEqual(response.status_code, 400)

        #  Test getting a list of currently added templates.
        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('templates'), [template.id, template2.id])


class DNCAPITestCase(CampaignDataMixin, BaseAPITestCase):
    dnc_export_url = reverse('dnc-export')

    def test_can_reset_dnc(self):
        mommy.make('InternalDNC', company=self.company1)
        mommy.make('InternalDNC', company=self.company2)
        mommy.make('Prospect', company=self.company1, do_not_call=True)
        self.assertEqual(InternalDNC.objects.filter(company=self.company1).count(), 1)
        self.assertEqual(Prospect.objects.filter(
            company=self.company1,
            do_not_call=True,
        ).count(), 1)
        self.assertEqual(InternalDNC.objects.filter(company=self.company2).count(), 1)

        url = f"{self.dnc_export_url}?clear_dnc=true"
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(InternalDNC.objects.filter(company=self.company1).count(), 0)
        self.assertEqual(Prospect.objects.filter(
            company=self.company1,
            do_not_call=True,
        ).count(), 0)
        self.assertEqual(InternalDNC.objects.filter(company=self.company2).count(), 1)


class CompanyCampaignStatsAPITestCase(CampaignDataMixin, BaseAPITestCase):

    def setUp(self):
        super(CompanyCampaignStatsAPITestCase, self).setUp()
        detail_kwargs = {'pk': self.company1.pk}
        self.company_campaign_meta_stats_url = reverse(
            'company-campaign-meta-stats',
            kwargs=detail_kwargs,
        )
        self.company_campaign_stats_url = reverse('company-campaign-stats', kwargs=detail_kwargs)

    def test_can_get_company_campaign_stats(self):
        # Create an archived campaign and verify it doesn't show in the active count.
        mommy.make('Campaign', company=self.company1, is_archived=True)
        valid_campaigns = self.company1.campaign_set.filter(is_archived=False)

        # Create data to test our situations
        self.george_campaign.total_leads = 3
        self.george_campaign.total_sms_sent_count = 100
        self.george_campaign.campaign_stats.has_delivered_sms_only_count = 87
        self.george_campaign.campaign_stats.save(update_fields=['has_delivered_sms_only_count'])
        self.george_campaign.save()

        cp = self.george_campaign.campaignprospect_set.first()
        cp.has_responded_via_sms = 'yes'
        cp.save()

        self.george_campaign2.total_leads = 1
        self.george_campaign2.total_sms_sent_count = 47
        self.george_campaign2.campaign_stats.has_delivered_sms_only_count = 40
        self.george_campaign2.campaign_stats.save(update_fields=['has_delivered_sms_only_count'])
        self.george_campaign2.save()

        # Create initial values to calculate our expectations
        expected_campaign_count = valid_campaigns.count()
        expected_new_lead_count = 0
        expected_total_sms_sent_count = 0
        delivery_rates = []
        response_rates = []

        # Aggregate the data for counts and rates
        for campaign in valid_campaigns:
            expected_new_lead_count += campaign.campaign_stats.total_leads
            expected_total_sms_sent_count += campaign.total_sms_sent_count
            delivery_rates.append(campaign.delivery_rate)
            response_rates.append(campaign.response_rate_sms)

        # Get the average for delivery and response rates
        expected_delivery_rate = round(sum(delivery_rates) / len(delivery_rates))
        expected_response_rate = round(sum(response_rates) / len(response_rates))

        response = self.george_client.get(self.company_campaign_meta_stats_url)
        self.assertEqual(response.data.get('active_campaign_count'), expected_campaign_count)
        self.assertEqual(response.data.get('new_lead_count'), expected_new_lead_count)
        self.assertEqual(response.data.get('total_sms_sent_count'), expected_total_sms_sent_count)
        self.assertEqual(response.data.get('delivery_rate'), expected_delivery_rate)
        self.assertEqual(response.data.get('response_rate'), expected_response_rate)

    def test_can_get_company_campaign_stats_without_active(self):
        # Test that a company without any active campaigns does not receive an error.
        for campaign in self.company2.campaign_set.all():
            campaign.is_archived = True
            campaign.save()

        valid_campaigns = self.company2.campaign_set.filter(is_archived=False)
        self.assertEqual(valid_campaigns.count(), 0)

        url = reverse('company-campaign-meta-stats', kwargs={'pk': self.company2.id})
        response = self.thomas_client.get(url)
        self.assertEqual(response.data.get('active_campaign_count'), 0)
        self.assertEqual(response.data.get('new_lead_count'), 0)
        self.assertEqual(response.data.get('total_sms_sent_count'), 0)
        self.assertEqual(response.data.get('delivery_rate'), 0)
        self.assertEqual(response.data.get('response_rate'), 0)

    def test_can_get_campaign_stats(self):
        # Create campaign stat data.
        today = timezone.now().date()
        yesterday = today - timedelta(days=1)
        mommy.make(
            'campaigns.CampaignDailyStats',
            campaign=self.george_campaign,
            date=today,
            delivered=5,
            sent=8,
            responses=2,
            skipped=1,
            auto_dead=0,
            new_leads=1,
        )
        mommy.make(
            'campaigns.CampaignDailyStats',
            campaign=self.george_campaign2,
            date=yesterday,
            delivered=9,
            sent=12,
            responses=3,
            skipped=2,
            auto_dead=1,
            new_leads=2,
        )
        mommy.make(
            'campaigns.CampaignDailyStats',
            campaign=self.john_campaign,
            date=today,
            delivered=8,
            sent=15,
            responses=2,
            skipped=4,
            auto_dead=2,
            new_leads=3,
        )

        george_response = self.george_client.get(self.company_campaign_stats_url)
        self.assertEqual(george_response.status_code, 200)
        response_data = george_response.json()

        expected_queryset = CampaignDailyStats.objects.filter(
            campaign__company=self.company1,
            sent__gt=0,
        )
        self.assertEqual(len(response_data), expected_queryset.count())

        # Test start_date
        george_response = self.george_client.get(
            self.company_campaign_stats_url,
            {'start_date': str(today)})
        self.assertEqual(george_response.status_code, 200)
        response_data = george_response.json()

        expected_queryset = CampaignDailyStats.objects.filter(
            campaign__company=self.company1,
            sent__gt=0,
            date__gte=today,
        )
        self.assertEqual(len(response_data), expected_queryset.count())

        # Test start_date and end_date
        george_response = self.george_client.get(
            self.company_campaign_stats_url,
            {'start_date': str(yesterday), 'end_date': str(yesterday)})
        self.assertEqual(george_response.status_code, 200)
        response_data = george_response.json()

        expected_queryset = CampaignDailyStats.objects.filter(
            campaign__company=self.company1,
            sent__gt=0,
            date__gte=yesterday,
            date__lte=yesterday,
        )
        self.assertEqual(len(response_data), expected_queryset.count())


class CompanyGoalAPITestCase(CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):

    list_endpoint_url = reverse('companygoal-list')
    # Custom action in companygoal viewset
    current_endpoint_url = reverse('companygoal-current')

    def setUp(self):
        super(CompanyGoalAPITestCase, self).setUp()

        self.company1_goal1 = mommy.make(
            'companies.CompanyGoal',
            company=self.company1,
            start_date=date.today(),
            end_date=date.today() + timedelta(weeks=1),
            budget=1000.00,
            leads=5,
            avg_response_time=10,
            new_campaigns=3,
            delivery_rate_percent=95,
        )
        self.company1_goal2 = mommy.make(
            'companies.CompanyGoal',
            company=self.company1,
            start_date=self.company1_goal1.end_date,
            end_date=self.company1_goal1.end_date + timedelta(days=30),
            budget=20000.00,
            leads=5,
            avg_response_time=10,
            new_campaigns=3,
            delivery_rate_percent=95,
        )
        self.company2_goal1 = mommy.make(
            'companies.CompanyGoal',
            company=self.company2,
            start_date=date.today(),
            end_date=date.today() + timedelta(days=30),
            budget=20000.00,
            leads=5,
            avg_response_time=10,
            new_campaigns=3,
            delivery_rate_percent=95,
        )

        self.detail_endpoint_url = reverse(
            'companygoal-detail',
            kwargs={'pk': self.company1_goal1.pk},
        )

    def test_anonymous_cant_get_company_goals(self):
        response = self.client.get(self.list_endpoint_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_their_company_goals(self):
        response = self.master_admin_client.get(self.list_endpoint_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 2)
        self.assertEqual(response.json().get('results')[1].get('id'), self.company1_goal1.id)
        self.assertEqual(response.json().get('results')[0].get('id'), self.company1_goal2.id)

    def test_user_cant_get_others_company_goals(self):
        response = self.company2_client.get(self.list_endpoint_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 1)
        self.assertEqual(response.json().get('results')[0].get('id'), self.company2_goal1.id)

    def test_anonymous_cant_get_company_goal(self):
        response = self.client.get(self.detail_endpoint_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_their_company_goal(self):
        response = self.master_admin_client.get(self.detail_endpoint_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.company1_goal1.id)

    def test_user_cant_get_others_company_goal(self):
        response = self.company2_client.get(self.detail_endpoint_url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_user_can_create_company_goal(self):
        new_goal = {
            'company': self.company1.pk,
            'start_date': date.today(),
            'end_date': date.today() + timedelta(days=30),
            'budget': 20000.00,
            'leads': 5,
            'avg_response_time': 10,
            'new_campaigns': 3,
            'delivery_rate_percent': 9,
        }
        response = self.master_admin_client.post(self.list_endpoint_url, new_goal)
        self.assertEqual(response.status_code, 201)

    def test_user_can_update_their_company_goal(self):
        response = self.master_admin_client.patch(self.detail_endpoint_url, {'new_campaigns': 4})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.company1_goal1.id)

    def test_user_cant_update_others_company_goal(self):
        response = self.company2_client.patch(self.detail_endpoint_url, {'new_campaigns': 4})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_user_cant_delete_others_company_goal(self):
        response = self.company2_client.delete(self.detail_endpoint_url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_user_can_delete_their_company_goal(self):
        response = self.master_admin_client.delete(self.detail_endpoint_url)
        self.assertEqual(response.status_code, 204)

    def test_user_can_get_current_company_goal(self):
        response = self.master_admin_client.get(self.current_endpoint_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.company1_goal1.id)


class LeadStageAPITestCase(AllUserRoleMixin, CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):
    list_url = reverse('leadstage-list')

    def setUp(self):
        super(LeadStageAPITestCase, self).setUp()
        self.detail_url = reverse(
            'leadstage-detail',
            kwargs={'pk': self.company1.leadstage_set.first().pk},
        )
        self.lead_stage_payload = {
            'lead_stage_title': 'Testing...',
            'sort_order': 42,
        }

    def test_user_can_get_their_company_leadstages(self):
        response = self.admin_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertTrue(len(results) > 0)

        for data in results:
            self.assertEqual(data.get('company'), self.company1.id)

    def test_user_can_create_leadstage(self):
        response = self.admin_client.post(self.list_url, self.lead_stage_payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data.get('isCustom'), True)
        self.assertEqual(data.get('company'), self.admin_user.profile.company.id)

    def test_user_can_update_their_leadstage(self):
        updated_title = 'Updated Title!'
        payload = {'lead_stage_title': updated_title}
        response = self.admin_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('leadStageTitle'), updated_title)

    def test_user_can_reorder_leadstage(self):
        # Update the reordering
        payload = {'sort_order': 77}
        response = self.admin_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('sortOrder'), 77)

    def test_user_can_update_full_leadstage_same(self):
        get_response = self.admin_client.get(self.detail_url)
        self.assertEqual(get_response.status_code, 200)

        payload = {
            'leadStageTitle': get_response.json().get('leadStageTitle'),
            'description': get_response.json().get('description'),
            'isCustom': get_response.json().get('isCustom'),
        }

        # Now let's try to update the same.
        put_response = self.admin_client.put(self.detail_url, payload)
        self.assertEqual(put_response.status_code, 200)

    def test_company_title_uniqueness(self):
        self.admin_client.post(self.list_url, self.lead_stage_payload)
        second = self.admin_client.post(self.list_url, self.lead_stage_payload)
        self.assertEqual(second.status_code, 400)

    def test_jrstaff_cannot_create_leadstage(self):
        response = self.jrstaff_client.post(self.list_url, self.lead_stage_payload)
        self.assertEqual(response.status_code, 403)

    def test_user_cant_update_other_leadstage(self):
        updated_title = 'Updated Title!'
        payload = {'lead_stage_title': updated_title}
        response = self.company2_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 404)

    def test_admin_can_delete_leadstage(self):
        response = self.admin_client.delete(self.detail_url)
        self.assertEqual(response.status_code, 204)

    def test_nonadmin_cant_delete_leadstage(self):
        response = self.staff_client.delete(self.detail_url)
        self.assertEqual(response.status_code, 403)


class CompanyModelTestCase(AdminUserMixin, CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):

    def test_can_translate_subscription_status(self):
        self.company1.subscription_status = 'Active'
        self.company1.save()
        self.assertEqual(self.company1.subscription_status, Company.SubscriptionStatus.ACTIVE)

        self.company1.subscription_status = 'Past Due'
        self.company1.save()
        self.assertEqual(self.company1.subscription_status, Company.SubscriptionStatus.PAST_DUE)

    def test_can_get_admin_profile(self):
        self.assertEqual(self.company1.admin_profile, self.master_admin_user.profile)

    def test_can_get_total_initial_send_sms_daily_limit(self):
        self.assertEqual(self.company1.total_initial_send_sms_daily_limit, 0)

        company1_market = mommy.make('Market', company=self.company1)
        company2_market = mommy.make('Market', company=self.company2)

        # Add a single valid phone number and verify that the daily limit is correct.
        mommy.make('PhoneNumber', market=company1_market)
        mommy.make('PhoneNumber', market=company2_market)
        mommy.make(
            'PhoneNumber',
            market=company1_market,
            status=PhoneNumber.Status.INACTIVE,
        )
        self.assertEqual(self.company1.total_initial_send_sms_daily_limit,
                         settings.MESSAGES_PER_PHONE_PER_DAY)

    def test_cant_save_multiple_primary_profiles(self):
        try:
            self.admin_user.profile.is_primary = True
            self.admin_user.profile.save()
            self.fail("Was able to save multiple primary profiles.")
        except ValidationError:
            pass

    def test_can_cancel_subscription(self):
        company = self.company1
        cancellation_request = mommy.make(
            'sherpa.SubscriptionCancellationRequest',
            company=self.company1,
            status=SubscriptionCancellationRequest.Status.ACCEPTED_PENDING,
        )
        self.assertEqual(company.subscription_status, Company.SubscriptionStatus.ACTIVE)
        self.assertNotEqual(company.subscription_id, '')

        # Get the initial data before cancellation.
        cancellation_request = company.cancellation_requests.first()
        self.assertNotEqual(
            cancellation_request.status, SubscriptionCancellationRequest.Status.COMPLETE)

        # Cancel the subscription and check all follow-up data expectations.
        company.cancel_subscription(subscription_cancellation=cancellation_request)

        # Verify that the cancellation request was finished.
        cancellation_request.refresh_from_db()
        self.assertEqual(
            cancellation_request.status, SubscriptionCancellationRequest.Status.COMPLETE)

    def test_company_profiles(self):
        admin_profile = self.admin_user.profile

        # Check that admin doesn't show up in company's profiles.
        assert admin_profile not in self.company2.profiles

        # Move admin user into company 1 and he should show up.
        self.company1.id = 1
        self.company1.save()
        admin_profile.company = self.company1
        admin_profile.save()
        assert admin_profile in self.company1.profiles

    def test_can_get_existing_matches_savings(self):
        company = self.company1
        self.assertEqual(company.total_skip_trace_savings, 0)

    def test_new_company_has_carrier_approved_templates(self):
        mommy.make('sms.CarrierApprovedTemplate', alternate_message='hi', is_active=True)
        mommy.make('sms.CarrierApprovedTemplate', is_active=False)
        company = mommy.make('sherpa.Company')
        self.assertTrue(company.carrier_templates.count() > 0)
        self.assertEqual(
            company.carrier_templates.count(),
            CarrierApprovedTemplate.objects.filter(is_active=True).count(),
        )


class CompanyTaskTestCase(CompanyTwoMixin, CompanyOneMixin, NoDataBaseTestCase):

    def test_cancellation_task(self):
        active_status = Company.SubscriptionStatus.ACTIVE
        cancelled_status = Company.SubscriptionStatus.CANCELED

        # Verify that the companies are setup for proper test.
        companies = [self.company1, self.company2]
        for company in companies:
            self.assertEqual(company.subscription_status, active_status)
            self.assertNotEqual(company.subscription_id, '')

        for company in companies:
            mommy.make(
                'sherpa.SubscriptionCancellationRequest',
                company=company,
                cancellation_date=timezone.now().date() - timedelta(days=1),
            )

        # On first run, the companies should not be updated since they are only pending cancel.
        process_cancellation_requests()
        for company in companies:
            self.assertEqual(company.subscription_status, active_status)
            self.assertNotEqual(company.subscription_id, '')

        # Now let's accept their cancellation, and next run should cancel them.
        for company in companies:
            cancel_request = company.cancellation_requests.first()
            cancel_request.status = SubscriptionCancellationRequest.Status.ACCEPTED_PENDING
            cancel_request.save()

        process_cancellation_requests()
        for company in companies:
            company.refresh_from_db()
            self.assertEqual(company.subscription_status, cancelled_status)
            self.assertEqual(company.subscription_id, '')


class CompanyCancellationFlowTestCase(AdminUserMixin, CompanyOneMixin, NoDataBaseTestCase):
    def setUp(self):
        self.cancel_url = reverse('cancellation-list')

    def test_discount_applied(self):
        payload = {
            'company': self.company1.id,
            'discount': True,
            'cancellationReason': SubscriptionCancellationRequest.Reason.PRICING,
            'cancellationReasonText': 'pricing',
        }
        response = self.master_admin_client.post(self.cancel_url, payload)
        self.assertEqual(response.status_code, 201)
        self.company1.refresh_from_db()
        cancel_request = self.company1.cancellation_requests
        self.assertTrue(cancel_request.exists())
        cancel_request = cancel_request.first()
        self.assertTrue(cancel_request.discount)
        self.assertEqual(cancel_request.status, SubscriptionCancellationRequest.Status.SAVED)

        response = self.master_admin_client.post(self.cancel_url, payload)
        self.assertEqual(response.status_code, 400)

    def test_pause_account(self):
        payload = {
            'pause': True,
            'cancellationReason': SubscriptionCancellationRequest.Reason.PAUSE,
            'cancellationReasonText': 'pausing',
        }
        response = self.master_admin_client.post(self.cancel_url, payload)
        self.assertEqual(response.status_code, 201)
        self.company1.refresh_from_db()
        cancel_request = self.company1.cancellation_requests
        self.assertTrue(cancel_request.exists())
        cancel_request = cancel_request.first()
        self.assertTrue(cancel_request.pause)

        response = self.master_admin_client.post(self.cancel_url, payload)
        self.assertEqual(response.status_code, 400)

    def test_downgrade_account(self):
        new_plan = product.SMS_CORE
        payload = {
            'newPlan': new_plan,
            'cancellationReason': SubscriptionCancellationRequest.Reason.PRICING,
            'cancellationReasonText': 'new plan',
        }
        response = self.master_admin_client.post(self.cancel_url, payload)
        self.assertEqual(response.status_code, 201)
        self.company1.refresh_from_db()
        cancel_request = self.company1.cancellation_requests
        self.assertTrue(cancel_request.exists())
        cancel_request = cancel_request.first()
        self.assertEqual(cancel_request.new_plan, new_plan)
        self.assertEqual(cancel_request.status, SubscriptionCancellationRequest.Status.SAVED)


class SubscriptionCancellationRequestModelTestCase(CompanyOneMixin, NoDataBaseTestCase):
    def setUp(self):
        self.cancellation_request = mommy.make(
            'SubscriptionCancellationRequest',
            company=self.company1,
        )

    def test_handle_pause(self):
        self.cancellation_request.pause = True
        self.cancellation_request.save()

        data = self.cancellation_request.handle_pause()
        self.assertEqual(type(data), dict)

        self.company1.subscription_status = Company.SubscriptionStatus.PAUSED
        self.company1.save()

        # Company is now in a paused state and `handle_pause` should raise an Exception.
        self.assertRaises(Exception, self.cancellation_request.handle_pause)

    def test_handle_discount(self):
        self.cancellation_request.discount = True
        self.cancellation_request.save()

        data = self.cancellation_request.handle_discount()
        self.assertEqual(type(data), dict)

        self.company1.cancellation_discount = True
        self.company1.save()

        # Company has had a discount and `handle_discount` should raise an Exception.
        self.assertRaises(Exception, self.cancellation_request.handle_discount)

    def test_handle_downgrade(self):
        # NOTE: Due to testing, subscriptions do not work.  Plan will ALWAYS be 'pro' on company.
        self.cancellation_request.new_plan = product.SMS_CORE
        self.cancellation_request.save()

        data = self.cancellation_request.handle_downgrade()
        self.assertEqual(type(data), dict)

        self.cancellation_request.new_plan = product.SMS_STARTER
        self.cancellation_request.save()

        # Company plan is pro and can only downgrade to core thus `handle_downgrade` should raise
        # an Exception.
        self.assertRaises(Exception, self.cancellation_request.handle_downgrade)


class TelephonyConnectionModelTestCase(CompanyOneMixin, NoDataBaseTestCase):

    def test_api_secret_is_encoded(self):
        connection = mommy.make('companies.TelephonyConnection', company=self.company1)
        my_secret = "c@tsM30w!!"
        connection.api_secret = my_secret
        connection.api_key = "cats123"
        connection.save()
        connection.refresh_from_db()
        self.assertTrue(isinstance(eval(connection.api_secret), bytes))
        self.assertNotEqual(connection.api_secret, connection.get_secret())
        self.assertEqual(connection.get_secret(), my_secret)

    def test_has_company_specified_telephony_integration(self):
        self.assertFalse(self.company1.has_company_specified_telephony_integration)
        mommy.make('companies.TelephonyConnection', company=self.company1)
        self.assertTrue(self.company1.has_company_specified_telephony_integration)


class TelephonyConnectionAPITestCase(
    AllUserRoleMixin,
    CompanyTwoMixin,
    CompanyOneMixin,
    NoDataBaseTestCase,
):
    """
    Test API to setup and update Telephony Connection settings.
    """
    default_data = {
        'api_key': 'cats123',
        'api_secret': 'meow456',
        'provider': 'telnyx',   # Setting to 'Telnyx' to get around unique constraint.
    }
    url = reverse('telephonyconnection-list')

    def setUp(self):
        super(TelephonyConnectionAPITestCase, self).setUp()
        self.connection = mommy.make('companies.TelephonyConnection', company=self.company1)
        self.connection2 = mommy.make('companies.TelephonyConnection', company=self.company2)
        detail_kwargs = {'pk': self.connection.pk}
        self.detail_url = reverse('telephonyconnection-detail', kwargs=detail_kwargs)
        detail_kwargs2 = {'pk': self.connection2.pk}
        self.detail_url_company2 = reverse('telephonyconnection-detail', kwargs=detail_kwargs2)

    def test_non_admin_user_cant_access(self):
        response = self.staff_client.post(self.url, self.default_data)
        self.assertEqual(response.status_code, 403)

    def test_admin_can_create_telephony_connection(self):
        response = self.admin_client.post(self.url, self.default_data)
        self.assertEqual(response.status_code, 201)
        connection_exists = TelephonyConnection.objects.filter(
            company=self.company1,
            api_key=self.default_data['api_key'],
        ).exists()
        self.assertTrue(connection_exists)

    def test_admin_can_update_telephony_connection(self):
        self.assertNotEqual(self.connection.api_key, self.default_data['api_key'])
        response = self.admin_client.patch(self.detail_url, self.default_data)
        self.assertEqual(response.status_code, 200)
        self.connection.refresh_from_db()
        self.assertEqual(self.connection.api_key, self.default_data['api_key'])

    def test_cant_update_other_company(self):
        response = self.admin_client.patch(self.detail_url_company2, self.default_data)
        self.assertEqual(response.status_code, 404)


class CompanyPodioIntegrationApiTestCase(
        AllUserRoleMixin,
        CompanyTwoMixin,
        CompanyOneMixin,
        NoDataBaseTestCase,
):
    def setUp(self):
        super(CompanyPodioIntegrationApiTestCase, self).setUp()
        self.podio_auth_create = reverse('crmpodiointegration-list')
        self.podio_auth_create_data = {
            "username": os.getenv("PODIO_TEST_USERNAME"),
            "password": os.getenv("PODIO_TEST_PW"),
        }
        self.test_prospect = 10
        self.podio_test_app_id = 25430237
        self.podio_test_workspace_id = 7356714

    def test_can_create_podio_integration(self):
        response = self.admin_client.post(
            self.podio_auth_create,
            self.podio_auth_create_data,
            format='json',
        )
        self.assertEqual(response.status_code, 201)
        self.assertTrue(
            CompanyPodioCrm.objects.filter(pk=response.data.get('integration_id')).exists(),
        )

    def test_can_delete_podio_integration(self):
        podio_auth_delete_url = reverse('crmpodiointegration-delete')
        response = self.admin_client.post(podio_auth_delete_url)
        status_code = response.status_code
        self.assertTrue(status_code == 404 or status_code == 204)

    def test_cant_create_map_fields_without_podio_integration(self):
        podio_map_fields_url = reverse('crmpodiofields-mapped-fields')
        data = {
            "podio_metadata": {
                "organization": {"value": 123456},
                "workspace": {"value": 1012131415},
                "application": {"value": 11235813},
            },
            "mapped_sherpa_fields": {
                "838383": {"values": ["address_address"], "config": {}},
                "123456": {"values": ["lead_stage"], "config": {}},
            },
        }
        response = self.admin_client.post(podio_map_fields_url, data, format='json')
        self.assertEqual(response.status_code, 404)

    def test_can_create_map_fields_with_podio_integration(self):
        mommy.make(
            'companies.CompanyPodioCrm',
            company=self.admin_user.profile.company,
            access_token="access-token",
            refresh_token="refresh-token",
            expires_in_token=123848,
        )
        podio_map_fields_url = reverse('crmpodiofields-mapped-fields')
        data = {
            "podio_metadata": {
                "organization": {"value": 123456},
                "workspace": {"value": 1012131415},
                "application": {"value": 11235813},
            },
            "mapped_sherpa_fields": {
                "838383": {"values": ["address_address"], "config": {}},
                "123456": {"values": ["lead_stage"], "config": {}},
            },
        }
        response = self.admin_client.post(podio_map_fields_url, data, format='json')
        self.assertEqual(response.status_code, 200)

    def test_can_get_podio_fields(self):
        podio_client = podio.PodioClient(
            self.admin_user.profile.company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
        )
        podio_client.authenticate(
            self.podio_auth_create_data["username"],
            self.podio_auth_create_data["password"],
        )
        podio_get_fields_url = reverse(
            'crmpodiofields-get-fields',
            kwargs={'pk': self.podio_test_app_id},
        )
        response = self.admin_client.get(podio_get_fields_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) > 0)

    def test_can_get_applications(self):
        podio_client = podio.PodioClient(
            self.admin_user.profile.company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
        )
        podio_client.authenticate(
            self.podio_auth_create_data["username"],
            self.podio_auth_create_data["password"],
        )
        url = reverse(
            'crmpodioapplications-get-all',
            kwargs={'pk': self.podio_test_workspace_id},
        )

        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) > 0)

    def test_cant_access_podio_api_without_integration(self):
        url = reverse('crmpodioorganizations-get-organizations')
        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_can_get_organizations(self):
        podio_client = podio.PodioClient(
            self.admin_user.profile.company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
        )
        podio_client.authenticate(
            self.podio_auth_create_data["username"],
            self.podio_auth_create_data["password"],
        )
        url = reverse(
            'crmpodioorganizations-get-organizations',
        )

        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) > 0)

    def test_can_get_sherpa_fields(self):
        url = reverse('crmpodiofields-get-sherpa-fields')
        response = self.admin_client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTrue(len(response.data) > 0)

    def test_prospect_not_pushed_to_podio_status(self):
        url = reverse(
            'crmpodioitems-get-crm-status',
            kwargs={'pk': self.test_prospect},
        )
        response = self.admin_client.post(url)
        self.assertEqual(response.status_code, 404)

    def test_prospect_pushed_to_podio_status(self):
        test_prospect = mommy.make(
            'sherpa.Prospect',
            company=self.company1,
        )
        mommy.make(
            'companies.PodioProspectItem',
            prospect=test_prospect,
            item_id=12,
        )
        url = reverse(
            'crmpodioitems-get-crm-status',
            kwargs={'pk': test_prospect.pk},
        )
        response = self.admin_client.post(url)
        self.assertEqual(response.status_code, 201)

    def test_get_podio_field_mappings_fail(self):
        url = reverse('crmpodiointegration-get-podio-field-mappings')
        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 404)

    def test_get_podio_field_mappings_success(self):
        mommy.make(
            'companies.PodioFieldMapping',
            company=self.admin_user.profile.company,
            fields={},
        )
        url = reverse('crmpodiointegration-get-podio-field-mappings')
        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_get_crm_integration(self):
        integration_test = mommy.make(
            'companies.CompanyPodioCrm',
            company=self.admin_user.profile.company,
        )
        url = reverse('crmpodiointegration-get-crm-integration')
        response = self.admin_client.get(url)
        self.assertEqual(integration_test.pk, response.data['pk'])

    def test_can_get_app_views(self):
        podio_client = podio.PodioClient(
            self.admin_user.profile.company,
            settings.PODIO_CLIENT_ID,
            settings.PODIO_CLIENT_SECRET,
        )
        podio_client.authenticate(
            self.podio_auth_create_data["username"],
            self.podio_auth_create_data["password"],
        )
        url = reverse(
            'crmpodioapplications-get-views',
            kwargs={'pk': self.podio_test_app_id},
        )
        response = self.admin_client.get(url)
        self.assertEqual(response.status_code, 200)
