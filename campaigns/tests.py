import csv
from datetime import timedelta
import io
import json
import uuid

from dateutil.parser import parse
from model_mommy import mommy

from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from companies.models import DownloadHistory, UploadBaseModel
from companies.utils import generate_campaign_prospect_filters
from markets.tests import MarketDataMixin
from prospects.resources import CampaignProspectResource
from prospects.utils import attempt_auto_verify
from sherpa.models import (
    Activity,
    Campaign,
    CampaignAccess,
    CampaignProspect,
    Company,
    LeadStage,
    PhoneNumber,
    Prospect,
    StatsBatch,
    UploadProspects,
    ZapierWebhook,
)
from sherpa.tests import (
    BaseAPITestCase,
    BaseTestCase,
    CompanyOneMixin,
    CompanyTwoMixin,
    NoDataBaseTestCase,
    StaffUserMixin,
)
from .models import CampaignNote
from .tasks import modify_campaign_daily_stats, record_skipped_send, transfer_campaign_prospects


class CampaignDataMixin(MarketDataMixin):

    valid_message = 'From {CompanyName}'

    def setUp(self):
        super(CampaignDataMixin, self).setUp()
        self.sms_template = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            alternate_message=self.valid_message,
            message=self.valid_message,
        )
        self.carrier_approved_template = mommy.make(
            'sms.CarrierApprovedTemplate',
            message='{FirstName}|{CompanyName}|{PropertyAddressFull}|{PropertyStreetAddress}|{UserFirstName}',  # noqa: E501
            alternate_message='Alternate message|{CompanyName}|{UserFirstName}',
            is_active=True,
            is_verified=True,
        )
        self.company1.carrier_templates.add(self.carrier_approved_template.id)
        self.george_campaign = mommy.make(
            'sherpa.Campaign',
            name="George Campaign 1",
            company=self.company1,
            market=self.market1,
            sms_template=self.sms_template,
        )
        campaign_stats1 = mommy.make(
            'campaigns.CampaignAggregatedStats',
            total_initial_sent_skipped=20,
            total_mobile=100,
        )
        self.george_campaign.campaign_stats = campaign_stats1
        self.george_campaign.save(update_fields=['campaign_stats'])
        campaign_stats2 = mommy.make(
            'campaigns.CampaignAggregatedStats',
            total_initial_sent_skipped=0,
            total_mobile=100,
        )
        self.george_campaign2 = mommy.make(
            'sherpa.Campaign',
            name="George Campaign 2",
            company=self.company1,
            owner=self.john_user.profile,
        )
        self.george_campaign2.campaign_stats = campaign_stats2
        self.george_campaign2.save(update_fields=['campaign_stats'])
        mommy.make(
            'sherpa.CampaignAccess',
            campaign=self.george_campaign2,
            user_profile=self.staff_user.profile,
        )
        campaign_stats3 = mommy.make(
            'campaigns.CampaignAggregatedStats',
            total_initial_sent_skipped=90,
            total_mobile=100,
        )
        self.george_campaign3 = mommy.make(
            'sherpa.Campaign',
            name="George Campaign 3",
            company=self.company1,
            market=self.market1,
        )
        self.george_campaign3.campaign_stats = campaign_stats3
        self.george_campaign3.save(update_fields=['campaign_stats'])
        mommy.make(
            'sherpa.CampaignAccess',
            campaign=self.george_campaign3,
            user_profile=self.staff_user.profile,
        )
        self.thomas_campaign = mommy.make(
            'sherpa.Campaign',
            name="Thomas Campaign",
            company=self.company2,
            market=self.company2.market_set.first(),
        )
        self.thomas_prospect = mommy.make(
            'sherpa.Prospect',
            company=self.company2,
            first_name='Stefan',
            last_name='Frei',
            phone_raw='4254448877',
        )
        mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.thomas_prospect,
            campaign=self.thomas_campaign,
        )
        mommy.make(
            'sherpa.PhoneType',
            company=self.company2,
            campaign=self.thomas_campaign,
            phone='4254448878',
        )
        self.address_full = '1 Rd Vaes Dothrak, DS 12345-6789'
        self.thomas_prospect2 = mommy.make(
            'sherpa.Prospect',
            company=self.company2,
            first_name='Khal',
            last_name='Drogo',
            property_address='1 Rd',
            property_city='Vaes Dothrak',
            property_state='DS',
            property_zip='12345-6789',
            mailing_address='1 Rd',
            mailing_city='Vaes Dothrak',
            mailing_state='DS',
            mailing_zip='12345-6789',
            phone_raw='4254448878',
        )
        self.thomas_campaign_prospect = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.thomas_prospect2,
            campaign=self.thomas_campaign,
        )
        address = mommy.make('properties.Address')
        self.george_prop = mommy.make('properties.Property', company=self.company1, address=address)
        self.george_prospect = mommy.make(
            'sherpa.Prospect',
            first_name='Jordan',
            last_name='Morris',
            company=self.company1,
            phone_raw='5097772222',
            sherpa_phone_number_obj=self.phone_number_1,
            related_record_id=uuid.uuid4(),
            prop=self.george_prop,
        )
        self.george_prospect2 = mommy.make(
            'sherpa.Prospect',
            first_name='Cristian',
            last_name='Roldan',
            company=self.company1,
            phone_raw='2062223333',
            sherpa_phone_number_obj=self.phone_number_2,
            phone_type='landline',
        )
        self.george_prospect3 = mommy.make(
            'sherpa.Prospect',
            company=self.company1,
            phone_raw='2068887777',
            sherpa_phone_number_obj=self.phone_number_1,
            phone_type='mobile',
        )
        mommy.make(
            'sherpa.PhoneType',
            company=self.company1,
            campaign=self.george_campaign,
            phone='4255557777',
            carrier='AT&T',
        )
        self.george_prospect4 = mommy.make(
            'sherpa.Prospect',
            company=self.company1,
            phone_raw='4255557777',
            phone_type='mobile',
        )
        self.george_campaign_prospect = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.george_prospect,
            campaign=self.george_campaign,
        )
        self.george_campaign_prospect2 = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.george_prospect2,
            campaign=self.george_campaign,
        )
        self.george_campaign_prospect3 = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.george_prospect3,
            campaign=self.george_campaign,
        )
        self.george_campaign_prospect4 = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.george_prospect4,
            campaign=self.george_campaign,
        )
        self.john_campaign = mommy.make(
            'sherpa.Campaign',
            company=self.company1,
            market=self.market1,
        )

        self.george_campaign_tag = mommy.make(
            'campaigns.CampaignTag',
            company=self.company1,
            name='Tag 1',
        )
        self.george_campaign_tag2 = mommy.make(
            'campaigns.CampaignTag',
            company=self.company1,
            name='Tag 2',
        )
        self.george_campaign.tags.add(self.george_campaign_tag)


class CampaignAPIMixin(CampaignDataMixin):
    """
    Mixin for shared functionality and urls for all the campaign test cases.
    """
    list_url = reverse('campaign-list')

    def setUp(self):
        super(CampaignAPIMixin, self).setUp()
        self.george_campaign_prospects_url = reverse(
            'campaign-batch-prospects',
            kwargs={'pk': self.george_campaign.pk},
        )
        self.george_campaign_url = reverse(
            'campaign-detail',
            kwargs={'pk': self.george_campaign.pk},
        )
        self.campaign_tag_list_url = reverse(
            'campaign-tags',
            kwargs={'pk': self.george_campaign.id},
        )


class CampaignAPITestCase(CampaignAPIMixin, BaseAPITestCase):

    def setUp(self):
        super(CampaignAPITestCase, self).setUp()
        self.export_url = reverse(
            'campaign-export-campaign-prospects', kwargs={'pk': self.george_campaign.pk})
        self.detail_url = reverse('campaign-detail', kwargs={'pk': self.george_campaign.pk})

        self.create_payload = {
            "market": self.george_campaign.market.id,
            "name": "new campaign",
        }

        self.webhook = mommy.make(
            'sherpa.ZapierWebhook',
            campaign=self.george_campaign_prospect.campaign,
            webhook_url='http://www.example.com',
            status='active',
        )
        self.direct_mail_campaign = mommy.make(
            'campaigns.DirectMailCampaign',
            campaign=self.george_campaign,
            order=mommy.make('campaigns.DirectMailOrder', drop_date=timezone.now().date()),
            return_address=mommy.make('campaigns.DirectMailReturnAddress'),
        )

    def test_anonymous_cant_get_campaign(self):
        response = self.client.get(self.george_campaign_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_their_campaigns(self):
        response = self.john_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 4)

    def test_user_cant_get_others_campaigns(self):
        response = self.thomas_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), self.company2.campaign_set.count())
        for campaign_data in response.json().get('results'):
            self.assertEqual(campaign_data.get('company'), self.company2.id)

    def test_user_can_get_their_campaign(self):
        response = self.john_client.get(self.george_campaign_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.george_campaign.id)
        self.assertEqual(response.json().get('name'), self.george_campaign.name)
        self.assertEqual(response.json().get('health'), 'good')
        self.assertEqual(response.json().get('priorityCount'), 0)

    def test_user_access_is_empty_when_all_users_added(self):
        for user in self.company1_users[:len(self.company1_users) - 1]:
            mommy.make(
                'sherpa.CampaignAccess',
                campaign=self.george_campaign,
                user_profile=user.profile,
            )

        # Test that the access user list has the same number we just added.
        response = self.john_client.get(self.george_campaign_url)
        self.assertTrue(len(response.json().get('access')) == len(self.company1_users) - 1)

        # Add missing user profile to campaign access.
        mommy.make(
            'sherpa.CampaignAccess',
            campaign=self.george_campaign,
            user_profile=self.company1_users[len(self.company1_users) - 1].profile,
        )

        # Test that the access user list is now empty because all users in the company has access.
        response = self.john_client.get(self.george_campaign_url)
        self.assertTrue(len(response.json().get('access')) == 0)

    def test_user_cant_get_others_campaign(self):
        response = self.thomas_client.get(self.george_campaign_url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_staff_cant_create_campaign(self):
        response = self.staff_client.post(self.list_url, self.create_payload)
        self.assertEqual(response.status_code, 403)

    def test_admin_user_can_create_campaign(self):
        payload = {**self.create_payload, "access": []}
        response = self.george_client.post(self.list_url, payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data.get('createdBy').get('id'), self.george_user.id)
        self.assertEqual(data.get('market').get('id'), self.george_campaign.market.id)

        # Verify that ALL users tied to company are found in new campaigns access list.
        campaign = Campaign.objects.get(pk=data.get('id'))
        access_count = campaign.campaignaccess_set.count()
        company_user_count = campaign.company.profiles.count()
        self.assertEqual(access_count, company_user_count)

    def test_direct_mail_campaign_creation_requires_valid_request(self):
        payload = {
            "campaign": {
                **self.create_payload,
                "access": [self.george_user.profile.id, self.john_user.profile.id],
            },
            "template": "S123",
            "agent_first_name": "Test",
            "agent_last_name": "Person",
            "return_address": "123 Fake St",
            "return_city": "Faketown",
            "return_state": "TX",
            "return_zip": "79423",
            "return_phone": 4444444444,
        }
        url = reverse('campaign-direct-mail')
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 400)

    def test_admin_user_can_create_direct_mail_campaign(self):
        payload = {
            "campaign": {
                **self.create_payload,
                "access": [self.george_user.profile.id, self.john_user.profile.id],
            },
            "drop_date": "2021-03-10",
            "from_id": self.george_user.id,
            "template": "S123",
            "budget_per_order": 500,
            "return_address": "123 Fake St",
            "return_city": "Faketown",
            "return_state": "TX",
            "return_zip": "79423",
            "return_phone": 4444444444,
            "note_for_processor": "asdfasd",
            "creative_type": "postcard",
        }

        url = reverse('campaign-direct-mail')
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertIsNotNone(data.get('id'))
        self.assertIsNotNone(data.get('campaign'))
        self.assertEqual(data.get('order').get('dropDate'), payload['drop_date'])

        url = reverse('campaign-detail', kwargs={'pk': response.json().get('campaign')})
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_can_get_direct_mail_templates(self):
        url = reverse('campaign-direct-mail-templates')
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)

    def test_can_get_direct_mail_target_date(self):
        # Test must include date
        url = f"{reverse('campaign-direct-mail-target-date')}"
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 400)

        # Test with an invalid target date
        url = f"{reverse('campaign-direct-mail-target-date')}?date=2021-05-01"
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('success'), False)

    def test_can_update_direct_mail_campaign(self):
        url = reverse('campaign-direct-mail-update', kwargs={'pk': self.direct_mail_campaign.pk})
        budget = self.direct_mail_campaign.budget_per_order + 100
        self.assertTrue(self.direct_mail_campaign.order.template != 'S128')
        payload = {
            'campaign': {'podio_push_email_address': 'test@test.com'},
            'budget_per_order': budget,
            'order': {'template': 'S128'},
            'return_address': {'address': {'city': 'Faketropolis'}},
        }
        response = self.george_client.patch(url, payload)
        self.assertEqual(response.status_code, 200)
        self.direct_mail_campaign.refresh_from_db()
        self.assertEqual(self.direct_mail_campaign.budget_per_order, budget)
        self.assertEqual(self.direct_mail_campaign.order.template, 'S128')
        self.assertEqual(self.direct_mail_campaign.return_address.address.city, 'Faketropolis')

    def test_can_get_stats_for_direct_mail_campaign(self):
        self.direct_mail_campaign.order.record_count = 4
        self.direct_mail_campaign.order.save(update_fields=['record_count'])

        mommy.make(
            'campaigns.DirectMailTrackingByPiece',
            status='delivered',
            order=self.direct_mail_campaign.order,
        )
        mommy.make(
            'campaigns.DirectMailTrackingByPiece',
            status='delivered',
            order=self.direct_mail_campaign.order,
        )
        mommy.make(
            'campaigns.DirectMailTrackingByPiece',
            status='returned',
            order=self.direct_mail_campaign.order,
        )
        mommy.make(
            'campaigns.DirectMailTrackingByPiece',
            status='redirected',
            order=self.direct_mail_campaign.order,
        )

        url = reverse(
            'campaign-direct-mail-aggregate-stats',
            kwargs={'pk': self.direct_mail_campaign.pk},
        )
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('totalDelivered'), 2)
        self.assertEqual(response.json().get('totalReturned'), 1)
        self.assertEqual(response.json().get('totalRedirected'), 1)
        self.assertEqual(response.json().get('deliveredRate'), .5)
        self.assertEqual(response.json().get('returnedRate'), .25)
        self.assertEqual(response.json().get('redirectedRate'), .25)

    def test_can_filter_campaigns_by_drect_mail(self):
        self.direct_mail_campaign.campaign.is_direct_mail = True
        self.direct_mail_campaign.campaign.save(update_fields=['is_direct_mail'])
        self.direct_mail_campaign.campaign.refresh_from_db()

        # Get all campaigns
        response = self.george_client.get(self.list_url)
        full_count = response.json().get('count')

        # Get Direct Mail only
        url = f"{self.list_url}?is_direct_mail=true"
        response = self.george_client.get(url)
        direct_mail_count = response.json().get('count')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(direct_mail_count < full_count)

        # Get SMS only
        url = f"{self.list_url}?is_direct_mail=false"
        response = self.george_client.get(url)
        sms_count = response.json().get('count')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(full_count, direct_mail_count + sms_count)

    def test_access_must_be_sent(self):
        """
        Test that shows `access` must be sent with the request to modify campaign access.
        If left out, access is ignored.
        """
        response = self.george_client.post(self.list_url, self.create_payload)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        campaign = Campaign.objects.get(pk=data.get('id'))
        access_count = campaign.campaignaccess_set.count()
        self.assertEqual(0, access_count)

    def test_admin_user_can_create_campaign_with_access(self):
        access_list = [self.george_user.profile.id, self.john_user.profile.id]
        payload = {**self.create_payload, "access": access_list}
        response = self.george_client.post(self.list_url, payload)
        self.assertEqual(response.status_code, 201)

        # Verify that the property `CompanyAccess` records were created.
        campaign = Campaign.objects.get(id=response.json().get('id'))
        self.assertEqual(campaign.campaignaccess_set.count(), len(access_list))

    def test_admin_user_always_included_in_campaign_access(self):
        access_list = [self.john_user.profile.id]
        payload = {**self.create_payload, "access": access_list}
        response = self.george_client.post(self.list_url, payload)

        # Verify that george was added, even though he forgot to add himself.
        campaign = Campaign.objects.get(id=response.json().get('id'))
        self.assertEqual(campaign.campaignaccess_set.count(), len(access_list) + 1)

    def test_user_can_update_their_campaign(self):
        update_campaign = {
            'name': 'Another test campaign',
        }
        response = self.george_client.patch(self.george_campaign_url, update_campaign)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('name'), update_campaign['name'])

    def test_user_cant_update_to_inactive_webhook(self):
        inactive_webhook = mommy.make(
            'sherpa.ZapierWebhook',
            company=self.company1,
            status=ZapierWebhook.Status.INACTIVE,
            webhook_url='https://www.example.com',
        )

        payload = {'zapier_webhook': inactive_webhook.id}
        response = self.george_client.patch(self.george_campaign_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('zapierWebhook'), None)

    def test_admin_user_can_update_campaign_access(self):
        campaign = self.george_campaign

        # Add access to the campaign.
        profiles = [self.george_user.profile, self.john_user.profile]
        for profile in profiles:
            CampaignAccess.objects.create(campaign=campaign, user_profile=profile)
        self.assertEqual(campaign.campaignaccess_set.count(), len(profiles))

        # Add a user to the campaign
        id_list = [profile.id for profile in profiles] + [self.staff_user.profile.id]
        payload = {'access': id_list}
        response = self.john_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 200)
        campaign.refresh_from_db()
        self.assertEqual(campaign.campaignaccess_set.count(), len(profiles) + 1)

        # Remove john from the campaign and ensure request user is maintainted.
        id_list = [self.staff_user.profile.id]
        payload = {'access': id_list}
        response = self.john_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 200)
        campaign.refresh_from_db()
        self.assertEqual(campaign.campaignaccess_set.count(), len(profiles))

        # Double check the access is correct.
        current_access_list = campaign.campaignaccess_set.values_list('user_profile', flat=True)
        assert self.george_user.profile.id not in current_access_list
        assert self.john_user.profile.id in current_access_list
        assert self.staff_user.profile.id in current_access_list

    def test_staff_user_cant_update_campaign(self):
        update_campaign = {
            'name': 'Another test campaign',
        }
        response = self.staff_client.patch(self.george_campaign_url, update_campaign)
        self.assertEqual(response.status_code, 403)

    def test_staff_user_uses_access_for_campaigns(self):
        response = self.staff_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 2)

    def test_user_cant_delete_campaign(self):
        response = self.george_client.delete(self.george_campaign_url)
        self.assertEqual(response.status_code, 405)
        self.assertEqual(response.json().get('detail'), 'Method "DELETE" not allowed.')

    def test_can_create_followup_campaign(self):
        self.george_campaign.zapier_webhook = self.webhook
        self.george_campaign.save(update_fields=['zapier_webhook'])
        url = reverse('campaign-followup', kwargs={'pk': self.george_campaign.id})
        payload = {
            'campaign_name': f'{self.george_campaign.name} Follow-Up',
        }
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get('name'), payload['campaign_name'])
        campaign = Campaign.objects.get(pk=response.json().get('id'))
        self.assertTrue(campaign.is_followup)
        self.assertEqual(self.webhook.pk, campaign.zapier_webhook.pk)

    def test_can_create_follow_campaign_with_filters(self):
        url = reverse('campaign-followup', kwargs={'pk': self.george_campaign.id})
        lead_stage = LeadStage.objects.get(
            company=self.company1,
            lead_stage_title='Initial Message Sent',
        )
        payload = {
            'campaign_name': 'Test Followup Campaign',
            'responded': True,
            'priority': True,
            'message_search': ['message'],
            'skip_reason': 'carrier',
            'lead_stage': [lead_stage.pk],
            'retain_numbers': True,
        }
        response = self.george_client.post(url, data=payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get('name'), payload['campaign_name'])
        campaign = Campaign.objects.get(pk=response.json().get('id'))
        self.assertTrue(campaign.is_followup)
        note = campaign.notes.first().text
        self.assertEqual(
            note,
            "Follow-up Filters\nLead Stage\n- Initial Message Sent\n\nInclude prospects who have "
            "responded?\nYes - only include the prospects that have replied\n\nProspects Who Are"
            "\n- Priority\n\nSkip Reason\nCarrier Skip\n\nKeywords\n- message\n\nRetain "
            "Initial Outgoing Numbers\nYes\n",
        )

    def test_can_filter_by_is_followup(self):
        # Verify we get nothing if there's no followup campaigns
        url = self.list_url + '?is_followup=true'
        response = self.george_client.get(url)
        self.assertEqual(len(response.json().get('results')), 0)

        # Create a followup campaign
        url_create_followup = reverse('campaign-followup', kwargs={'pk': self.george_campaign.id})
        payload = {
            'campaign_name': 'Test followup',
        }
        self.george_client.post(url_create_followup, payload)

        # Verify that campaigns come back filtered by followup
        total_followup = Campaign.objects.filter(
            company=self.george_user.profile.company,
            is_followup=True,
        ).count()
        response = self.george_client.get(url)
        self.assertEqual(len(response.json().get('results')), total_followup)

        # Verify that we can also filter by non-followup campaigns
        url = self.list_url + '?is_followup=false'
        total_not_followup = Campaign.objects.filter(
            company=self.george_user.profile.company).exclude(is_followup=True).count()
        response = self.george_client.get(url)
        self.assertEqual(len(response.json().get('results')), total_not_followup)

    def test_can_filter_by_owner_id(self):
        profile = self.john_user.profile
        url = self.list_url + f'?owner={profile.id}'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), Campaign.objects.filter(owner=profile).count())

        for campaign in results:
            self.assertEqual(campaign.get('owner'), profile.id)

    def test_can_filter_market(self):
        url = self.list_url + f'?market={self.market1.id}'
        response = self.george_client.get(url)

        for campaign_data in response.json().get('results'):
            self.assertEqual(campaign_data.get('market').get('id'), self.market1.id)

    def test_can_filter_on_archived(self):
        # Setup an archived campaign
        self.george_campaign2.is_archived = True
        self.george_campaign2.save()

        url = self.list_url + '?is_archived=false'
        response = self.george_client.get(url)

        results = response.json().get('results')
        # Verify the archived campaign is not returned
        for campaign_data in results:
            campaign = Campaign.objects.get(id=campaign_data.get('id'))
            self.assertFalse(campaign.is_archived)

    def test_can_filter_on_unread(self):
        # Setup an unread campaign
        self.george_campaign2.has_unread_sms = True
        self.george_campaign2.save()

        url = self.list_url + '?has_unread_sms=true'
        response = self.george_client.get(url)

        results = response.json().get('results')
        # Verify the unread campaign is not returned
        for campaign_data in results:
            campaign = Campaign.objects.get(id=campaign_data.get('id'))
            self.assertTrue(campaign.has_unread_sms)

    def test_can_filter_on_name(self):
        search_string = self.george_campaign.name[3:]
        url = self.list_url + f'?search={search_string}'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)
        for result in results:
            self.assertTrue(search_string in result.get('name'))

        # Verify that name can combine with another filter.
        url += '&is_archived=false'
        response2 = self.george_client.get(url)
        self.assertEqual(len(response2.json().get('results')), 1)
        url = url.replace('is_archived=false', 'is_archived=true')
        response3 = self.george_client.get(url)
        self.assertEqual(len(response3.json().get('results')), 0)

    def test_can_order_by_create_date(self):
        url = self.list_url + '?ordering=created_date'
        response = self.george_client.get(url)
        results = response.json().get('results')

        self.assertTrue(len(results) > 1)

        last_date = None
        for campaign_data in results:
            date = parse(campaign_data.get('createdDate'))
            if last_date:
                self.assertTrue(date > last_date)
            last_date = date

    def test_can_order_by_alpha(self):
        """
        This test has been flaky and needs to be removed until we figure out why.
        """
        # Add some extra records in non-alpha order.
        mommy.make('sherpa.Campaign', name='c', company=self.company1)
        mommy.make('sherpa.Campaign', name='4', company=self.company1)
        mommy.make('sherpa.Campaign', name='r', company=self.company1)
        mommy.make('sherpa.Campaign', name='m', company=self.company1)

        url = self.list_url + '?ordering=name'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertTrue(len(results) > 1)

        previous_name = None
        for campaign_data in results:
            name = campaign_data.get('name')
            if previous_name:
                self.assertTrue(name.lower() > previous_name.lower())
            previous_name = name

        # Reverse the order.
        url = self.list_url + '?ordering=-name'
        response = self.george_client.get(url)
        results = response.json().get('results')
        previous_name = None
        for campaign_data in results:
            name = campaign_data.get('name')
            if previous_name:
                self.assertTrue(name.lower() < previous_name.lower())
            previous_name = name

    def test_export_campaign_does_not_require_filter(self):
        response = self.george_client.get(self.export_url)
        self.assertEqual(response.status_code, 200)

    def test_export_requires_valid_leadstage(self):
        response = self.george_client.get(self.export_url + '?lead_stage=88888')
        self.assertEqual(response.status_code, 404)

    def test_export_campaign_is_priority_unread_true_not_require_lead_stage(self):
        export_url = self.export_url + '?is_priority_unread=true'
        response = self.george_client.get(export_url)
        self.assertEqual(response.status_code, 200)

    def test_user_can_export_campaign_csv(self):
        # Prepare proper data form the prospects.
        prospect1 = self.george_prospect
        prospect2 = self.george_prospect2
        prospect1.lead_stage = self.company1.leadstage_set.first()
        prospect1.save()
        prospect2.lead_stage = self.company1.leadstage_set.last()
        prospect2.save()

        # Verify that a csv response is returned.
        export_url = self.export_url + f'?lead_stage={prospect1.lead_stage.id}'
        response = self.george_client.get(export_url)
        download_id = response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = self.george_campaign.build_export_query(
            generate_campaign_prospect_filters(download.filters),
        )
        resource = CampaignProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        self.assertEqual(response.status_code, 200)

        # Verify some minimal data in the csv.
        for data in csv_data:
            self.assertEqual(data.get('First Name'), prospect1.first_name)
            self.assertEqual(data.get('Phone'), prospect1.phone_display)
            self.assertEqual(data.get('Stage'), prospect1.lead_stage.lead_stage_title)

    def test_export_campaign_with_is_priority_unread(self):
        # Verify if there's nothing marked 'is_priority' or 'has_unread_sms' nothing's returned
        export_url = self.export_url + '?is_priority_unread=true'
        response = self.george_client.get(export_url)
        download_id = response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = self.george_campaign.build_export_query(
            generate_campaign_prospect_filters(download.filters),
        )
        resource = CampaignProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        self.assertEqual(response.status_code, 200)
        count = len([data for data in csv_data])
        self.assertEqual(count, 0)
        self.assertEqual(response.status_code, 200)

        # Verify that prospects marked 'is_priority' are returned
        self.george_prospect.is_priority = True
        self.george_prospect.save(update_fields=['is_priority'])
        response = self.george_client.get(export_url)
        download_id = response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = self.george_campaign.build_export_query(
            generate_campaign_prospect_filters(download.filters),
        )
        resource = CampaignProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        self.assertEqual(response.status_code, 200)
        count = len([data for data in csv_data])
        self.assertEqual(count, 1)
        self.assertEqual(response.status_code, 200)

        # Verify that prospects marked 'has_unread_sms' are returned
        self.george_prospect2.has_unread_sms = True
        self.george_prospect2.save(update_fields=['has_unread_sms'])
        response = self.george_client.get(export_url)
        download_id = response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = self.george_campaign.build_export_query(
            generate_campaign_prospect_filters(download.filters),
        )
        resource = CampaignProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        self.assertEqual(response.status_code, 200)
        count = len([data for data in csv_data])
        self.assertEqual(count, 2)

    def test_can_export_by_phone_type(self):
        campaign = self.george_campaign
        export_url = self.export_url

        # Modify the data to test all export situations.
        cp_queryset = campaign.campaignprospect_set.all()
        cp_queryset[0].prospect.phone_type = 'landline'
        cp_queryset[1].prospect.phone_type = ''
        cp_queryset[2].is_litigator = True

        for campaign_prospect in cp_queryset:
            campaign_prospect.save()

        response = self.george_client.get(export_url + '?phone_type=invalid')
        self.assertEqual(response.status_code, 400)

        def _check_csv_data(phone_type, expected_queryset, modify_count=0):
            """
            Verify that the data returned in the csv is what is expected.

            :param phone_type: The phone type string to be added to the url.
            :param expected_queryset: The queryset to compare results with the expected.
            :param modify_count: Integer value to account for extra headers.
            :param extra_headers: Verify that extra headers are in the csv download.
            """
            url = f'{export_url}?phone_type={phone_type}'
            response = self.george_client.get(url)
            download_id = response.json()['id']
            download = DownloadHistory.objects.get(uuid=download_id)
            queryset = campaign.build_export_query(
                generate_campaign_prospect_filters(download.filters),
            )
            resource = CampaignProspectResource().export(download, queryset)
            csv_data = csv.DictReader(io.StringIO(resource.csv))
            csv_count = len([data for data in csv_data])
            count = csv_count - modify_count
            expected_count = expected_queryset.count()
            self.assertEqual(count, expected_count)

        # Export the mobile numbers
        expected_queryset = cp_queryset.filter(prospect__phone_type='mobile')
        _check_csv_data('mobile', expected_queryset)

        # Export the landline numbers
        expected_queryset = cp_queryset.filter(prospect__phone_type='landline')
        _check_csv_data('landline', expected_queryset)

        # Export the litigators
        expected_queryset = cp_queryset.filter(is_litigator=True)
        _check_csv_data('litigator', expected_queryset)

        # Export the other numbers
        expected_queryset = cp_queryset.exclude(
            Q(prospect__phone_type='mobile') | Q(prospect__phone_type='landline'))
        _check_csv_data('other', expected_queryset)

        # Export all numbers
        expected_queryset = cp_queryset
        _check_csv_data('all', cp_queryset)

    def test_can_get_campaign_stats(self):
        # Setup data so that we can test some data.
        campaign = self.george_campaign
        campaign.save()

        mommy.make('campaigns.InitialResponse', campaign=campaign)

        # Send some bulk messages
        delivered = 0
        for i in range(10):
            delivered += 1
            mommy.make('sherpa.SMSMessage', campaign=campaign)
        campaign.campaign_stats.has_delivered_sms_only_count = delivered
        campaign.campaign_stats.save(update_fields=['has_delivered_sms_only_count'])

        expected_attempts = 10
        expected_sent = expected_attempts - campaign.campaign_stats.total_skipped
        mommy.make('sherpa.StatsBatch', campaign=campaign, send_attempt=expected_attempts)

        # Send the request.
        url = reverse('campaign-stats', kwargs={'pk': self.george_campaign.id})
        response = self.george_client.get(url)

        # Verify the expected data in the response data.
        data = response.json()
        self.assertEqual(response.status_code, 200)

        campaign.campaign_stats.refresh_from_db()
        # Campaign stats
        self.assertEqual(data.get('health'), campaign.health)
        self.assertEqual(data.get('totalSmsSentCount'), expected_sent)
        self.assertEqual(data.get('totalProspects'), campaign.total_properties)
        self.assertEqual(data.get('totalResponses'), campaign.initialresponse_set.count())
        self.assertEqual(data.get('totalLeads'), campaign.campaign_stats.total_leads)
        self.assertEqual(data.get('deliveryRate'), campaign.get_delivery_rate())
        self.assertEqual(data.get('responseRate'), campaign.get_response_rate())

        # Messaging stats
        self.assertEqual(data.get('dailySendLimit'),
                         campaign.market.total_initial_send_sms_daily_limit)
        self.assertEqual(data.get('totalSendsAvailable'), campaign.market.total_sends_available)
        self.assertEqual(data.get('totalSkipped'), campaign.campaign_stats.total_skipped)
        self.assertEqual(
            data.get('totalInitialSmsUndelivered'),
            campaign.total_initial_sms_undelivered / campaign.total_sent,
        )
        self.assertEqual(data.get('autoDeadPercentage'), campaign.auto_dead_percentage)
        self.assertEqual(
            data.get('totalAutoDeadCount'),
            campaign.campaign_stats.total_auto_dead_count,
        )

        # Import stats
        self.assertEqual(data.get('phoneNumberCount'), campaign.total_prospects)
        self.assertEqual(data.get('totalMobile'), campaign.campaign_stats.total_mobile)
        self.assertEqual(data.get('totalLandline'), campaign.campaign_stats.total_landline)
        self.assertEqual(data.get('totalPhoneOther'), campaign.campaign_stats.total_phone_other)
        self.assertEqual(data.get('totalLitigators'), campaign.total_litigators)
        self.assertEqual(data.get('totalInternalDnc'), campaign.total_internal_dnc)

    def test_can_get_full_campaign_list(self):
        url = reverse('campaign-full')
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)

        # Verify the count is as expected.
        expected_count = self.company1.campaign_set.filter(is_archived=False).count()
        self.assertEqual(len(response.json()), expected_count)

    def test_campaign_percent_complete_filter(self):
        response = self.george_client.get(self.list_url)
        data = response.json()
        self.assertEqual(data['count'], 4)

        response = self.george_client.get(self.list_url, {'percent_complete_max': 20})
        data = response.json()
        self.assertEqual(data['count'], 2)

        response = self.george_client.get(self.list_url, {'percent_complete_min': 90})
        data = response.json()
        self.assertEqual(data['count'], 1)

        response = self.george_client.get(
            self.list_url,
            {'percent_complete_min': 19, 'percent_complete_max': 90},
        )
        data = response.json()
        self.assertEqual(data['count'], 2)

    def test_campaign_percent_complete_sorting(self):
        response = self.george_client.get(self.list_url, {'ordering': '-percent'})
        data = response.json()['results']
        percent_ordering = [90, 20, 0, None]
        for i, p in enumerate(percent_ordering):
            self.assertEqual(p, data[i]['percentComplete'])

        response = self.george_client.get(self.list_url, {'ordering': 'percent'})
        data = response.json()['results']
        percent_ordering = [0, 20, 90, None]
        for i, p in enumerate(percent_ordering):
            self.assertEqual(p, data[i]['percentComplete'])

    def test_campaign_issue(self):
        ci1 = mommy.make(
            'campaigns.CampaignIssue',
            code='TEST1',
            issue_desc='This is just a test.',
            suggestions=['Do nothing', 'Stay calm'],
        )
        ci2 = mommy.make(
            'campaigns.CampaignIssue',
            code='TEST2',
            issue_desc='This is another test.',
            suggestions=['Do something', 'Panic'],
        )
        self.george_campaign.issues.add(ci1, ci2)
        url = reverse('campaign-issues', kwargs={'pk': self.george_campaign.pk})
        response = self.george_client.get(url)
        data = response.json()

        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]['code'], 'TEST1')
        self.assertEqual(len(data[1]['suggestions']), 2)

    def test_can_bulk_tag_prospects(self):
        # Tests both adding and removing tags.
        tag1 = mommy.make(
            'PropertyTag',
            company=self.george_user.profile.company,
            name='test',
        )
        tag2 = mommy.make(
            'PropertyTag',
            company=self.george_user.profile.company,
            name='test2',
        )
        tag3 = mommy.make(
            'PropertyTag',
            company=self.george_user.profile.company,
            name='test3',
        )

        # Test adding two tags to ALL prospects in campaign.
        url = reverse('campaign-tag-prospects', kwargs={'pk': self.george_campaign.id})
        payload = {
            'add': [tag1.pk, tag2.pk],
        }
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        prospects = [
            self.george_prospect,
            self.george_prospect2,
            self.george_prospect3,
            self.george_prospect4,
        ]

        # Verify all prospects were updated and each have 2 tags.
        for prospect in prospects:
            if prospect.prop:
                self.assertEqual(prospect.prop.tags.count(), 2)

        # Verify a random prospect to make sure the two tags added were the ones used above.
        self.assertEqual(
            list(self.george_prospect.prop.tags.order_by('name').values_list('name', flat=True)),
            ['test', 'test2'],
        )

        # Test adding and removing at the same time.  End result should be all tags from above
        # are removed with the new tag being the only tag.
        payload = {
            'add': [tag3.pk],
            'remove': [tag1.pk, tag2.pk],
        }
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 200)

        # Verify that all prospects were updated and each have only one tag.
        for prospect in prospects:
            if prospect.prop:
                self.assertEqual(prospect.prop.tags.count(), 1)

        # Verify that a random prospect has the actual tag we added.
        self.assertEqual(
            list(self.george_prospect.prop.tags.order_by('name').values_list('name', flat=True)),
            ['test3'],
        )

    def test_can_add_tags_to_campaign(self):
        tags_qs = self.company1.campaigntag_set.all()
        url = self.campaign_tag_list_url
        id_list = [tag.id for tag in tags_qs]
        response = self.george_client.post(url, {'tags': id_list})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.george_campaign.tags.count(), tags_qs.count())

    def test_can_remove_tags_to_campaign(self):
        tag = self.company1.campaigntag_set.first()
        self.george_campaign.tags.add(tag)
        self.assertEqual(self.george_campaign.tags.count(), 1)

        # Now send the request to remove the tag.
        response = self.george_client.delete(self.campaign_tag_list_url, {'tags': [tag.id]})
        self.assertEqual(response.status_code, 200)
        self.george_campaign.refresh_from_db()
        self.assertEqual(self.george_campaign.tags.count(), 0)


class UploadProspectsAPITestCase(CampaignAPIMixin, BaseAPITestCase):
    map_fields_url = reverse('uploadprospect-map-fields')
    list_url = reverse('uploadprospect-list')

    def setUp(self):
        super(UploadProspectsAPITestCase, self).setUp()
        self.upload_prospect = mommy.make(
            'UploadProspects',
            company=self.george_user.profile.company,
            campaign=self.george_campaign,
        )
        self.detail_url = reverse('uploadprospect-detail', kwargs={'pk': self.upload_prospect.pk})

    def test_cant_get_other_companies_upload_prospect(self):
        response = self.thomas_client.get(self.detail_url)
        self.assertEqual(response.status_code, 404)

    def test_can_get_upload_prospect(self):
        response = self.george_client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)

    def test_can_filter_prospect_uploads_by_campaign(self):
        mommy.make(
            'UploadProspects',
            company=self.george_user.profile.company,
            campaign=self.george_campaign2,
        )
        mommy.make(
            'UploadProspects',
            company=self.george_user.profile.company,
            campaign=self.george_campaign2,
        )

        url = f'{self.list_url}?campaign={self.george_campaign.id}'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        for result in response.json()['results']:
            self.assertEqual(result.get('campaign'), self.george_campaign.id)

    def test_list_does_not_return_setups(self):
        mommy.make(
            'UploadProspects',
            company=self.george_user.profile.company,
            campaign=self.george_campaign2,
            status=UploadBaseModel.Status.SETUP,
        )

        response = self.george_client.get(self.list_url)
        for upload_instance in response.json()['results']:
            self.assertNotEqual(upload_instance.get('status'), UploadBaseModel.Status.SETUP)

    def test_can_get_upload_prospect_percent_complete(self):
        self.upload_prospect.total_rows = 100
        self.upload_prospect.last_row_processed = 10
        self.upload_prospect.save(update_fields=['total_rows', 'last_row_processed'])
        self.upload_prospect.refresh_from_db()
        response = self.george_client.get(self.detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('percentComplete'), '10%')

    def test_cant_map_fields_without_authentication(self):
        response = self.client.get(self.map_fields_url, {})
        self.assertEqual(response.status_code, 401)

    def test_must_send_valid_data_to_map_fields(self):
        response = self.george_client.post(self.map_fields_url, {})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()['detail'],
            'Must send `headers_matched`, `valid_data`, `uploaded_filename` in request.',
        )

    def test_can_map_fields(self):
        headers_matched = [
            {'letter': 'A', 'matched_key': 'street'},
            {'letter': 'B', 'matched_key': 'city'},
            {'letter': 'C', 'matched_key': 'state'},
            {'letter': 'D', 'matched_key': 'zipcode'},
            {'letter': 'E', 'matched_key': 'phone_1_number'},
        ]
        valid_data = [
            {
                'street': '123 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
                'phone_1_number': 5555555555,
            },
            {
                'street': '123 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
                'phone_1_number': 5555555556,
            },
        ]
        data = {
            'valid_data': json.dumps(valid_data),
            'headers_matched': json.dumps(headers_matched),
            'uploaded_filename': 'test.csv',
            'campaign': self.george_campaign.pk,
        }

        # Verify can map fields
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(response.status_code, 201)
        upload = UploadProspects.objects.get(id=response.json()['id'])
        self.assertIsNotNone(upload)
        self.assertEqual(upload.uploaded_filename, 'test.csv')
        self.assertEqual(upload.total_rows, 2)
        self.assertEqual(upload.created_by, self.george_user)
        for i, h in enumerate([header['matched_key'] for header in headers_matched]):
            if h != 'phone_1_number':
                self.assertEqual(getattr(upload, f'{h}_column_number'), i)
            else:
                self.assertEqual(getattr(upload, 'phone_1_number'), i)

        # Verify confirm additional cost logic
        self.george_user.profile.company.monthly_upload_limit = 0
        self.george_user.profile.company.subscription_id = 'gh3mcb'
        self.george_user.profile.company.invitation_code = self.invitation_code1
        self.george_user.profile.company.save()
        self.george_user.profile.company.refresh_from_db()
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(int(response.json().get('exceedsCount', 0)), len(valid_data))
        data['confirm_additional_cost'] = True
        response = self.george_client.post(self.map_fields_url, data)
        self.assertTrue(int(response.json().get('confirmAdditionalCost', False)))

    def test_can_map_fields_no_campaign(self):
        headers_matched = [
            {'letter': 'A', 'matched_key': 'street'},
            {'letter': 'B', 'matched_key': 'city'},
            {'letter': 'C', 'matched_key': 'state'},
            {'letter': 'D', 'matched_key': 'zipcode'},
            {'letter': 'E', 'matched_key': 'phone_1_number'},
        ]
        valid_data = [
            {
                'street': '123 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
                'phone_1_number': 5555555555,
            },
            {
                'street': '124 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
                'phone_1_number': 5555555556,
            },
            {
                'street': '125 Address Lane',
                'city': 'Testville',
                'state': 'TX',
                'zipcode': '79423',
            },
        ]
        data = {
            'valid_data': json.dumps(valid_data),
            'headers_matched': json.dumps(headers_matched),
            'uploaded_filename': 'test.csv',
        }

        # Verify can map fields
        response = self.george_client.post(self.map_fields_url, data)
        self.assertEqual(response.status_code, 201)
        upload = UploadProspects.objects.get(id=response.json()['id'])
        self.assertIsNotNone(upload)

    def test_can_start_upload_no_tags(self):
        response = self.george_client.get(f'{self.detail_url}start_upload/')
        self.assertEqual(response.status_code, 200)

    def test_can_start_upload_with_tags(self):
        tag1 = mommy.make('PropertyTag', company=self.company1, name='tag1')
        tag2 = mommy.make('PropertyTag', company=self.company1, name='tag2')
        tags = f'{tag1.id},{tag2.id}'
        response = self.george_client.get(f'{self.detail_url}start_upload/?tags={tags}')
        self.assertEqual(response.status_code, 200)

    def test_failed_start_upload_with_bad_tags(self):
        valid = mommy.make('PropertyTag', company=self.company1, name='tag1')
        wrong_company = mommy.make('PropertyTag', company=self.company2, name='wrongcompany')
        tags = f'{valid.id},not_an_id'
        response = self.george_client.get(f'{self.detail_url}start_upload/?tags={tags}')
        self.assertEqual(response.status_code, 400)
        self.assertTrue("must be integers" in response.json()['tags'][0])
        tags = f'{valid.id},{wrong_company.id}'
        response = self.george_client.get(f'{self.detail_url}start_upload/?tags={tags}')
        self.assertEqual(response.status_code, 400)
        self.assertTrue("do not exist" in response.json()['tags'][0])

    def test_auto_verify(self):
        # Verify that the prospect is auto verified.
        prospects = []
        for i in range(3):
            status = Prospect.OwnerVerifiedStatus.VERIFIED if i != 2 \
                else Prospect.OwnerVerifiedStatus.OPEN
            prospects.append(
                mommy.make(
                    'sherpa.Prospect',
                    first_name='Same',
                    last_name='Name',
                    property_address='123 Ditto Ave',
                    owner_verified_status=status,
                ),
            )
        p = prospects[2]
        self.assertEqual(p.owner_verified_status, Prospect.OwnerVerifiedStatus.OPEN)
        attempt_auto_verify(p)
        p.refresh_from_db()
        self.assertEqual(p.owner_verified_status, Prospect.OwnerVerifiedStatus.VERIFIED)

        # Verify that the prospect is not auto verified.
        prospects = []
        for i in range(3):
            status = Prospect.OwnerVerifiedStatus.UNVERIFIED if i != 2 \
                else Prospect.OwnerVerifiedStatus.OPEN
            prospects.append(
                mommy.make(
                    'sherpa.Prospect',
                    first_name='Same',
                    last_name='Name',
                    property_address='123 Ditto Ave',
                    owner_verified_status=status,
                ),
            )
        p = prospects[2]
        self.assertEqual(p.owner_verified_status, Prospect.OwnerVerifiedStatus.OPEN)
        attempt_auto_verify(p)
        p.refresh_from_db()
        self.assertEqual(p.owner_verified_status, Prospect.OwnerVerifiedStatus.OPEN)


class StatsBatchAPITestCase(CampaignDataMixin, BaseAPITestCase):

    list_url = reverse('statsbatch-list')

    def setUp(self):
        super(StatsBatchAPITestCase, self).setUp()
        for i in range(5):
            mommy.make(
                'sherpa.StatsBatch',
                campaign=self.george_campaign,
                sent=100,
                received=62,
                batch_number=i,
            )

        # Make an additional one for different campaign
        mommy.make('sherpa.StatsBatch', campaign=self.george_campaign2)

    def test_stats_batch_requires_auth(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 401)

    def test_stats_batch_list_requires_campaign(self):
        response = self.george_client.get(self.list_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()[0],
                         'Must supply `campaign` in query parameter.')

    def test_can_only_get_own_company_stats_batch(self):
        url = self.list_url + f'?campaign={self.john_campaign.id}'
        response = self.john_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 0)

    def test_can_get_stats_batch(self):
        url = self.list_url + f'?campaign={self.george_campaign.id}'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(results), self.george_campaign.statsbatch_set.count())


class CampaignProspectAPITestCase(CampaignAPIMixin, BaseAPITestCase):

    def setUp(self):
        super(CampaignProspectAPITestCase, self).setUp()
        self.company1.outgoing_company_names = ['A test company']
        self.company1.use_sender_name = True
        self.company1.save()

    def test_anonymous_cant_get_campaign_prospects(self):
        response = self.client.get(self.george_campaign_prospects_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_their_batch_prospects(self):
        self.category = mommy.make(
            'sms.SMSTemplateCategory',
            title='testcat',
            company=self.company1,
        )
        mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message='message {CompanyName}',
            alternate_message='altmessage {CompanyName}',
            category=self.category,
            sort_order=1,
        )
        response = self.george_client.get(
            self.george_campaign_prospects_url,
            {'sms_category': self.category.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            len(response.json()),
            CampaignProspect.objects.filter(
                prospect__company=self.company1,
                prospect__phone_type='mobile',
            ).count(),
        )

    def test_user_can_update_sms_template(self):
        self.george_campaign.sms_template = None
        self.george_campaign.save()

        new_template = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=self.valid_message,
            alternate_message=self.valid_message,
        )
        new_template2 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=self.valid_message + ' 2',
            alternate_message=self.valid_message + ' 2',
        )
        base_url = self.george_campaign_prospects_url

        # Update sms template when campaign does not have one.
        response = self.george_client.get(f'{base_url}?sms_template={new_template.id}')
        self.assertEqual(response.status_code, 200)
        self.george_campaign.refresh_from_db()
        self.assertEqual(self.george_campaign.sms_template, new_template)

        # Update to a new sms template.
        response = self.george_client.get(f'{base_url}?sms_template={new_template2.id}')
        self.assertEqual(response.status_code, 200)
        self.george_campaign.refresh_from_db()
        self.assertEqual(self.george_campaign.sms_template, new_template2)

    def test_batch_prospects_requires_payment(self):
        self.company1.subscription_status = Company.SubscriptionStatus.PAST_DUE
        self.company1.save()
        response = self.george_client.get(self.george_campaign_prospects_url)
        self.assertEqual(response.status_code, 403)
        self.company1.subscription_status = Company.SubscriptionStatus.ACTIVE
        self.company1.save()

    def test_invalid_outgoing_data(self):
        self.company1.outgoing_company_names = []
        self.company1.outgoing_first_names = []
        self.company1.use_sender_name = False
        self.company1.save()
        response = self.george_client.get(self.george_campaign_prospects_url)
        self.assertEqual(response.status_code, 400)

    def test_invalid_template(self):
        self.sms_template.message = 'invalid'
        self.sms_template.save()
        response = self.george_client.get(self.george_campaign_prospects_url)
        self.assertEqual(response.status_code, 400)

    def test_user_cant_get_others_batch_prospects(self):
        response = self.thomas_client.get(self.george_campaign_prospects_url)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')


class CampaignBulkExportAPITestCase(CampaignAPIMixin, BaseAPITestCase):

    bulk_export_url = reverse('campaign-bulk-export')

    def setUp(self):
        super(CampaignBulkExportAPITestCase, self).setUp()
        self.id_list = [self.george_campaign.id, self.george_campaign2.id, self.george_campaign3.id]

    def test_anonymous_cant_bulk_export_campaigns(self):
        response = self.client.post(
            self.bulk_export_url,
            {'id_list': self.id_list},
        )
        self.assertEqual(response.status_code, 401)

    def test_user_can_bulk_export_campaigns(self):
        response = self.george_client.get(
            self.bulk_export_url,
            {'id': self.id_list},
        )

        self.assertEqual(response.status_code, 200)


class CampaignBulkArchiveAPITestCase(CampaignAPIMixin, BaseAPITestCase):

    endpoint_url = reverse('campaign-bulk-archive')

    def setUp(self):
        super(CampaignBulkArchiveAPITestCase, self).setUp()
        self.id_list = [self.george_campaign.id, self.george_campaign2.id, self.george_campaign3.id]

    def test_anonymous_cant_bulk_archive_campaigns(self):
        response = self.client.put(
            self.endpoint_url,
            {'id_list': self.id_list, 'is_archived': True},
        )
        self.assertEqual(response.status_code, 401)

    def test_user_can_bulk_archive_campaigns(self):
        response = self.george_client.post(
            self.endpoint_url,
            {'id_list': self.id_list, 'is_archived': True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('rowsUpdated'), 3)
        campaign_response = self.george_client.get(self.george_campaign_url)
        self.assertEqual(campaign_response.status_code, 200)
        self.assertEqual(campaign_response.json().get('isArchived'), True)

    def test_user_can_bulk_unarchive_campaigns(self):
        response = self.george_client.post(
            self.endpoint_url,
            {'id_list': self.id_list, 'is_archived': False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('rowsUpdated'), 3)
        campaign_response = self.george_client.get(self.george_campaign_url)
        self.assertEqual(campaign_response.status_code, 200)
        self.assertEqual(campaign_response.json().get('isArchived'), False)

    def test_user_cant_bulk_archive_others_campaigns(self):
        response = self.thomas_client.post(
            self.endpoint_url,
            {'id_list': self.id_list, 'is_archived': True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('rowsUpdated'), 0)

    def test_user_cant_bulk_unarchive_others_campaigns(self):
        response = self.thomas_client.post(
            self.endpoint_url,
            {'id_list': self.id_list, 'is_archived': False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('rowsUpdated'), 0)


class CampaignTaskTestCase(CampaignDataMixin, BaseTestCase):

    def test_transfer_campaign_prospects(self):
        # Setup a campaign prospect to be transfered.
        cp = self.george_campaign.campaignprospect_set.first()
        cp.has_responded_via_sms = 'no'
        cp.sent = True
        cp.save()

        cp.prospect.phone_type = 'mobile'
        cp.prospect.save()

        # Create the followup campaign and transfer campaign prospects.
        current_count = self.company1.campaign_set.count()
        original_campaign = self.george_campaign
        followup_campaign = self.george_campaign.create_followup(self.george_user, 'Followup Name')
        transfer_campaign_prospects(original_campaign.id, followup_campaign.id)

        # Verify data after transfer.
        self.assertEqual(self.company1.campaign_set.count(), current_count + 1)
        self.assertEqual(followup_campaign.created_by, self.george_user)
        self.assertEqual(followup_campaign.campaignprospect_set.count(), 1)

    def test_can_create_daily_stats(self):
        # Create data to properly test the task.
        expected_sent = 5
        expected_delivered = 3
        expected_responses = 1

        for i, _ in enumerate(range(expected_sent)):
            message = mommy.make(
                'sherpa.SMSMessage', campaign=self.george_campaign)

            # Set some to delivered.
            if i % 2 == 0:
                message.message_status = 'delivered'
                message.save()

        mommy.make('campaigns.InitialResponse', campaign=self.george_campaign)

        instance = modify_campaign_daily_stats(self.george_campaign.id, str(timezone.now().date()))
        self.assertEqual(expected_sent, instance.sent)
        self.assertEqual(expected_delivered, instance.delivered)
        self.assertEqual(expected_responses, instance.responses)

    def test_create_campaign_with_filters(self):
        # Test filtering of response and DNC or priority.
        self.george_campaign_prospect.has_responded_via_sms = 'yes'
        self.george_campaign_prospect.sent = True
        self.george_campaign_prospect.save(update_fields=['has_responded_via_sms', 'sent'])

        self.george_prospect.phone_type = Prospect.PhoneType.MOBILE
        self.george_prospect.save(update_fields=['phone_type'])

        # This will be found in the filter but ignored due to `phone_type`.
        self.george_campaign_prospect2.has_responded_via_sms = 'yes'
        self.george_campaign_prospect2.sent = True
        self.george_campaign_prospect2.save(update_fields=['has_responded_via_sms', 'sent'])

        self.george_prospect2.phone_type = Prospect.PhoneType.LANDLINE
        self.george_prospect2.save(update_fields=['phone_type'])

        # This should not be included because their response is 'no'.
        self.george_campaign_prospect3.has_responded_via_sms = 'no'
        self.george_campaign_prospect3.sent = True
        self.george_campaign_prospect3.save(update_fields=['has_responded_via_sms', 'sent'])

        self.george_prospect3.phone_type = Prospect.PhoneType.MOBILE
        self.george_prospect3.is_priority = True
        self.george_prospect3.save(update_fields=['phone_type', 'is_priority'])

        filters = {
            'responded': True,
        }

        new_campaign = self.george_campaign.create_followup(self.george_user, 'followup name')

        transfer_campaign_prospects(self.george_campaign.id, new_campaign.id, filters=filters)
        new_campaign.refresh_from_db()
        self.assertEqual(new_campaign.campaignprospect_set.all().count(), 1)

    def test_can_update_total_mobile(self):
        campaign = self.george_campaign
        expected_count = campaign.campaignprospect_set.filter(
            prospect__phone_type=Prospect.PhoneType.MOBILE,
        ).count()

        # Just make total mobile be invalid, so we can check that it's updated correctly.
        campaign.campaign_stats.total_mobile = expected_count + 1
        campaign.campaign_stats.save(update_fields=['total_mobile'])

        # Now update and it should be back to correct.
        campaign.update_campaign_stats()
        campaign.refresh_from_db()
        self.assertEqual(campaign.campaign_stats.total_mobile, expected_count)

    def test_record_skipped_send(self):
        cp = self.george_campaign_prospect
        cp.skipped = True
        cp.save()

        initial_skipped = cp.campaign.campaign_stats.total_skipped
        record_skipped_send(cp.id)
        cp.campaign.refresh_from_db()
        self.assertEqual(cp.campaign.campaign_stats.total_skipped, initial_skipped + 1)


class CampaignModelTestCase(CampaignDataMixin, BaseTestCase):
    """
    Test functionality around campaign models methods and signals.
    """
    def test_set_has_priority(self):
        self.assertFalse(self.george_campaign.has_priority)
        self.george_prospect.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_campaign.has_priority)
        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.VERIFIED,
        )

    def test_prospect_multiple_campaigns_priority(self):
        mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.george_prospect,
            campaign=self.george_campaign2,
        )

        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.OPEN,
        )
        # Add priority to george prospect and check campaigns.
        self.george_prospect.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.george_campaign2.refresh_from_db()
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_campaign.has_priority)
        self.assertTrue(self.george_campaign2.has_priority)
        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.VERIFIED,
        )

        # Remove priority to george prospect and check campaigns.
        self.george_prospect.toggle_is_priority(self.george_user, False)
        self.george_campaign.refresh_from_db()
        self.george_campaign2.refresh_from_db()
        self.assertFalse(self.george_campaign.has_priority)
        self.assertFalse(self.george_campaign2.has_priority)

        self.george_prospect.refresh_from_db()
        # Prospect should still be verified
        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.VERIFIED,
        )

    def test_add_already_priority(self):
        self.george_campaign.has_priority = True
        self.george_campaign.save()
        self.george_prospect.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.assertTrue(self.george_campaign.has_priority)

    def test_remove_single_priority(self):
        self.george_prospect.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.assertTrue(self.george_campaign.has_priority)
        self.george_prospect.toggle_is_priority(self.george_user, False)
        self.george_campaign.refresh_from_db()
        self.assertFalse(self.george_campaign.has_priority)

    def test_remove_multiple_priority(self):
        self.george_prospect.toggle_is_priority(self.george_user, True)
        self.george_prospect2.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.assertTrue(self.george_campaign.has_priority)

        self.george_prospect.toggle_is_priority(self.george_user, False)
        self.george_campaign.refresh_from_db()
        self.assertTrue(self.george_campaign.has_priority)

        self.george_prospect2.toggle_is_priority(self.george_user, False)
        self.george_campaign.refresh_from_db()
        self.assertFalse(self.george_campaign.has_priority)

    def test_get_can_get_campaign_progress(self):
        # Test if there are no mobile numbers.
        self.george_campaign.campaign_stats.total_initial_sent_skipped = 20
        self.george_campaign.campaign_stats.total_mobile = 0
        self.george_campaign.campaign_stats.save(
            update_fields=['total_mobile', 'total_initial_sent_skipped'])
        self.assertEqual(self.george_campaign.percent_complete, None)

        # Test when we haven't sent any messages yet
        self.george_campaign.campaign_stats.total_initial_sent_skipped = 0
        self.george_campaign.campaign_stats.total_mobile = 20
        self.george_campaign.campaign_stats.save(
            update_fields=['total_mobile', 'total_initial_sent_skipped'])
        self.assertEqual(self.george_campaign.percent_complete, 0)

        # Test partial progress
        self.george_campaign.campaign_stats.total_initial_sent_skipped = 5
        self.george_campaign.campaign_stats.total_mobile = 20
        self.george_campaign.campaign_stats.save(
            update_fields=['total_mobile', 'total_initial_sent_skipped'])
        self.assertEqual(self.george_campaign.percent_complete, 25)

    def _create_filtering_dates(self):
        # Create all the date objects that we can loop through to satisfy the conditions.
        now = timezone.now()
        start = now - timedelta(days=100)
        before = start - timedelta(days=1)
        end = now - timedelta(days=10)
        after = end + timedelta(days=1)
        dates = [before, start, end, after]
        return dates

    def _create_messages(self):
        campaign = self.george_campaign
        # Create messages for each of our dates.
        dates = self._create_filtering_dates()
        for date in dates:
            message = mommy.make('sherpa.SMSMessage', campaign=campaign)
            message.dt = date
            message.save()

        # Update the aggregated fields for george's campaign.
        campaign.total_sms_sent_count = len(dates)
        campaign.save()

    def test_can_get_sms_time_range(self):
        dates = self._create_filtering_dates()
        start = dates[1]
        end = dates[2]

        self._create_messages()
        queryset = self.george_campaign.get_bulk_sent_messages(
            start_date=start,
            end_date=end,
        )
        self.assertEqual(queryset.count(), 2)

        # Can generate sms time range with no dates.
        queryset = self.george_campaign.get_bulk_sent_messages()
        self.assertEqual(queryset.count(), 4)

        # Can generate sms time range with just `start_date`.
        queryset = self.george_campaign.get_bulk_sent_messages(start_date=start)
        self.assertEqual(queryset.count(), 3)

        # Can generate sms time range with just `end_date`.
        queryset = self.george_campaign.get_bulk_sent_messages(end_date=end)
        self.assertEqual(queryset.count(), 3)

    def test_can_get_campaign_prospect_activities(self):
        dates = self._create_filtering_dates()
        start = dates[1]
        end = dates[2]

        # Create lead generated activity for these dates.
        activity_title = Activity.Title.ADDED_QUALIFIED
        for date in dates:
            activity = mommy.make(
                'sherpa.Activity',
                prospect=self.george_prospect,
                title=activity_title,
            )
            activity.date_utc = date
            activity.save()

        # Create one more activity with a different title.
        mommy.make(
            'sherpa.Activity',
            prospect=self.george_prospect,
            title=Activity.Title.ADDED_AUTODEAD,
        )

        # Create one more activity from a prospect in different campaign.
        self.george_campaign_prospect4.campaign = self.george_campaign2
        self.george_campaign_prospect4.save()

        mommy.make(
            'sherpa.Activity',
            prospect=self.george_prospect4,
            title=activity_title,
        )

        queryset = self.george_campaign.get_prospect_activities(
            start_date=start,
            end_date=end,
            activity_title=activity_title,
        )
        self.assertEqual(queryset.count(), 2)

        # Can retrieve prospect activity with no dates.
        queryset = self.george_campaign.get_prospect_activities(activity_title=activity_title)
        self.assertEqual(queryset.count(), 4)

        # Can retrieve prospect activity with just `start_date`.
        queryset = self.george_campaign.get_prospect_activities(
            activity_title=activity_title,
            start_date=start,
        )
        self.assertEqual(queryset.count(), 3)

        # Can retrieve prospect activity with just `end_date`.
        queryset = self.george_campaign.get_prospect_activities(
            activity_title=activity_title,
            end_date=end,
        )
        self.assertEqual(queryset.count(), 3)

    def test_can_get_delivery_rating_with_time_range(self):
        dates = self._create_filtering_dates()
        start = dates[1]
        end = dates[2]

        # Create message and result data.
        campaign = self.george_campaign
        stats_batch = mommy.make('sherpa.StatsBatch', campaign=campaign)
        for index, date in enumerate(dates):
            message = mommy.make(
                'sherpa.SMSMessage',
                prospect=self.george_prospect,
                campaign=campaign,
            )
            # Need to update date after, since it's `auto_now_add`.
            message.dt = date
            message.save()

            # Create 2x undelivered and 2x delivered.
            is_delivered = index % 2 == 0
            mommy.make(
                'sms.SMSResult',
                sms=message,
                status='delivered' if is_delivered else 'delivery_failed',
            )

            # Update the aggregated fields for george's campaign.
            campaign.total_sms_sent_count += 1
            stats_batch.send_attempt += 1
            if is_delivered:
                campaign.campaign_stats.has_delivered_sms_only_count += 1
                stats_batch.delivered += 1
            stats_batch.save(update_fields=['delivered', 'send_attempt'])
            campaign.save()

        # Check an empty campaign.
        delivery_rate1 = self.george_campaign2.get_delivery_rate()
        self.assertEqual(delivery_rate1, 0)

        # Check for delivery rates for the campaign that we've sent messages to.
        delivery_rate1 = campaign.get_delivery_rate()
        self.assertEqual(delivery_rate1, 50)
        delivery_rate2 = campaign.get_delivery_rate(start_date=start)
        self.assertEqual(delivery_rate2, 33)
        delivery_rate3 = campaign.get_delivery_rate(end_date=end)
        self.assertEqual(delivery_rate3, 67)
        delivery_rate4 = campaign.get_delivery_rate(start_date=start, end_date=end)
        self.assertEqual(delivery_rate4, 50)

    def test_can_get_response_rate_by_time_range(self):
        dates = self._create_filtering_dates()
        start = dates[1]
        end = dates[2]

        campaign = self.george_campaign
        prospect = self.george_prospect
        for index, date in enumerate(dates):
            # Create a message for each date.
            message = mommy.make('sherpa.SMSMessage', prospect=prospect, campaign=campaign)
            # Need to update date after, since it's `auto_now_add`.
            message.dt = date
            message.save()

        campaign.total_sms_sent_count = len(dates)
        campaign.save()

        # Create a response on start date
        response = mommy.make('campaigns.InitialResponse', campaign=campaign)
        response.created = start
        response.save()

        # Check an empty campaign.
        response_rate1 = self.george_campaign2.get_response_rate()
        self.assertEqual(response_rate1, 0)

        # Check for response rates for our campaign.
        response_rate1 = campaign.get_response_rate()
        self.assertEqual(response_rate1, 25)
        response_rate2 = campaign.get_response_rate(start_date=start)
        self.assertEqual(response_rate2, 33)
        response_rate3 = campaign.get_response_rate(end_date=end)
        self.assertEqual(response_rate3, 33)
        response_rate4 = campaign.get_response_rate(start_date=start, end_date=end)
        self.assertEqual(response_rate4, 50)

    def test_cant_create_followup_within_timeframe(self):
        self.assertFalse(self.george_campaign.can_create_followup)

        # Modify the created date so that it's before the threshold.
        before_date = timezone.now() - timedelta(days=self.company1.threshold_days + 1)
        self.george_campaign.created_date = before_date
        self.george_campaign.save()
        self.assertTrue(self.george_campaign.can_create_followup)

    def test_access_for_followup_campaign(self):
        followup = self.george_campaign2.create_followup(self.george_user, "Followup")
        self.assertEqual(followup.campaignaccess_set.get().user_profile, self.staff_user.profile)

        followup = self.george_campaign.create_followup(self.george_user, "Followup 2")
        self.assertTrue(
            len(followup.campaignaccess_set.all().values_list('user_profile_id', flat=True)) == 0,
        )
        self.assertEqual(followup.followup_from, self.george_campaign)

    def test_correct_block_reason_returned(self):
        # Verify the block reason is because of subscription.
        company = self.george_campaign.company
        company.subscription_status = Company.SubscriptionStatus.CANCELED
        company.save()
        self.assertEqual(self.george_campaign.block_reason, 'subscription')

        # Verify that insufficient numbers can block the campaign.
        company.subscription_status = Company.SubscriptionStatus.ACTIVE
        company.save()
        self.assertEqual(self.george_campaign.block_reason, 'active-numbers')

        # Verify that the campaign is valid if within time range. We need to set this up to pass for
        # either situation, because it depends on the time.
        for i in range(20):
            mommy.make(
                'sherpa.PhoneNumber',
                market=self.george_campaign.market,
                provider='telnyx',
                status=PhoneNumber.Status.ACTIVE,
            )

        if company.is_messaging_disabled:
            self.assertEqual(self.george_campaign.block_reason, 'time')
        else:
            self.assertEqual(self.george_campaign.block_reason, '')

    def test_can_get_current_batch(self):
        mommy.make('sherpa.StatsBatch', campaign=self.george_campaign, batch_number=1, sent=100)
        expected = mommy.make('sherpa.StatsBatch', campaign=self.george_campaign, batch_number=2,
                              sent=1)
        self.assertEqual(self.george_campaign.current_batch, expected)


class StatsBatchModelTestCase(CampaignDataMixin, BaseTestCase):

    def setUp(self):
        super(StatsBatchModelTestCase, self).setUp()
        self.stats_batch = mommy.make('sherpa.StatsBatch', campaign=self.george_campaign)

    def test_sending_without_stats_batch_creates_new(self):
        self.assertEqual(self.john_campaign.statsbatch_set.count(), 0)
        stats_batch = self.john_campaign.update_stats_batch()
        stats_batch.refresh_from_db()
        self.assertTrue(isinstance(stats_batch, StatsBatch))
        self.assertEqual(stats_batch.send_attempt, 1)
        self.assertEqual(self.john_campaign.statsbatch_set.count(), 1)

    def test_sending_increments_stats_batch(self):
        self.george_campaign.update_stats_batch()
        self.stats_batch.refresh_from_db()
        self.assertEqual(self.stats_batch.send_attempt, 1)

    def test_sending_with_full_stats_batch_creates_new(self):
        for _ in range(101):
            self.george_campaign.update_stats_batch()
        self.assertEqual(self.george_campaign.statsbatch_set.last().send_attempt, 100)
        self.assertEqual(self.george_campaign.statsbatch_set.count(), 2)
        self.assertEqual(self.george_campaign.statsbatch_set.first().send_attempt, 1)


class CampaignNoteAPITestCase(CampaignDataMixin, BaseAPITestCase):

    notes_list_url = reverse('campaignnote-list')

    def setUp(self):
        super(CampaignNoteAPITestCase, self).setUp()
        self.george_note = mommy.make('campaigns.CampaignNote', campaign=self.george_campaign,
                                      created_by=self.john_user)
        self.george_note2 = mommy.make('campaigns.CampaignNote', campaign=self.george_campaign2,
                                       created_by=self.george_user)
        self.thomas_note = mommy.make('campaigns.CampaignNote', campaign=self.thomas_campaign,
                                      created_by=self.thomas_user)
        self.note_detail_url = reverse('campaignnote-detail', kwargs={'pk': self.george_note.id})

    def test_user_can_get_their_notes(self):
        response = self.george_client.get(self.notes_list_url)
        results = response.json().get('results')
        self.assertEqual(
            len(results), CampaignNote.objects.filter(campaign__company=self.company1).count())

    def test_user_can_filter_by_campaign(self):
        url = self.notes_list_url + f'?campaign={self.george_campaign.id}'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), self.george_campaign.notes.count())

        for note in results:
            self.assertEqual(note.get('campaign'), self.george_campaign.id)

    def test_user_can_create_note(self):
        payload = {
            'text': 'this is a test.',
            'campaign': self.george_campaign.id,
        }
        response = self.george_client.post(self.notes_list_url, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get('createdBy').get('id'), self.george_user.id)

    def test_user_can_edit_their_note(self):
        new_note = 'This is the new note.'
        payload = {'text': new_note}
        response = self.george_client.patch(self.note_detail_url, payload)
        data = response.json()
        self.assertEqual(data.get('text'), new_note)

    def test_user_cant_edit_others_note(self):
        new_note = 'This is the new note.'
        payload = {'note': new_note}
        response = self.thomas_client.patch(self.note_detail_url, payload)
        self.assertEqual(response.status_code, 404)

    def test_user_can_delete_their_note(self):
        response = self.george_client.delete(self.note_detail_url)
        self.assertEqual(response.status_code, 204)

    def test_user_cant_delete_others_note(self):
        response = self.thomas_client.delete(self.note_detail_url)
        self.assertEqual(response.status_code, 404)

    def test_note_creator_is_expanded(self):
        url = self.notes_list_url
        response = self.george_client.get(url)
        results = response.json().get('results')

        for note_data in results:
            self.assertEqual(type(note_data.get('createdBy')), dict)


class CampaignTagAPITestCase(StaffUserMixin, CompanyOneMixin, CompanyTwoMixin, NoDataBaseTestCase):
    tag_list_url = reverse('campaigntag-list')

    def setUp(self):
        super(CampaignTagAPITestCase, self).setUp()
        self.company1_tag = mommy.make('campaigns.CampaignTag', company=self.company1)
        self.tag_detail_url = reverse('campaigntag-detail', kwargs={'pk': self.company1_tag.pk})
        mommy.make('campaigns.CampaignTag', company=self.company2)

    def test_can_get_company_tags(self):
        response = self.staff_client.get(self.tag_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data), self.company1.campaigntag_set.count())

    def test_admin_can_create_campaign_tag(self):
        payload = {'name': 'My Cool Tag'}
        response = self.master_admin_client.post(self.tag_list_url, payload)
        self.assertEqual(response.status_code, 201)

    def test_admin_can_edit_campaign_tag(self):
        tag_name = 'My Super Cool Tag'
        payload = {'name': tag_name}
        response = self.master_admin_client.patch(self.tag_detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('name'), tag_name)

    def test_admin_can_delete_campaign_tag(self):
        response = self.master_admin_client.delete(self.tag_detail_url)
        self.assertEqual(response.status_code, 204)

    def test_staff_cant_modify_campaign_tag(self):
        response = self.staff_client.delete(self.tag_detail_url)
        self.assertEqual(response.status_code, 403)

        response = self.staff_client.patch(self.tag_detail_url, {'name': 'updated name'})
        self.assertEqual(response.status_code, 403)
