import csv
from datetime import datetime, time, timedelta
import io

from dateutil.parser import parse
from model_mommy import mommy

from django.conf import settings
from django.urls import reverse
from django.utils import timezone

from campaigns.tests import CampaignDataMixin
from companies.models import DownloadHistory, PodioFieldMapping
from companies.resources import PodioResource
from prospects.models import ProspectTag
from prospects.resources import ProspectResource
from prospects.utils import is_empty_search, record_phone_number_opt_outs
from services.crm.podio.utils import fetch_data_to_sync
from sherpa.models import (
    Activity,
    Campaign,
    CampaignProspect,
    Company,
    InternalDNC,
    LeadStage,
    LitigatorList,
    LitigatorReportQueue,
    PhoneNumber,
    Prospect,
    SMSPrefillText,
)
from sherpa.tests import BaseAPITestCase, BaseTestCase, CompanyOneMixin, NoDataBaseTestCase
from sms import OPT_OUT_LANGUAGE


class ProspectAPITestCase(CampaignDataMixin, BaseAPITestCase):
    prospect_list_url = reverse('prospect-list')
    prospect_search_url = reverse('prospect-search')
    # prospect_es_search_url = reverse('prospect-prospect-search')

    def setUp(self):
        super(ProspectAPITestCase, self).setUp()
        detail_kwargs = {'pk': self.george_prospect.id}
        self.prospect_detail_url = reverse('prospect-detail', kwargs=detail_kwargs)
        self.send_message_url = reverse('prospect-send-message', kwargs=detail_kwargs)
        self.push_to_zapier_url = reverse('prospect-push-to-zapier', kwargs=detail_kwargs)
        self.email_to_podio_url = reverse('prospect-email-to-podio', kwargs=detail_kwargs)
        self.mark_as_read_url = reverse('prospect-mark-as-read', kwargs=detail_kwargs)
        self.prospect_search_url = reverse('prospect-search')
        self.export_search_url = reverse('prospect-export')
        self.quick_replies_url = reverse('prospect-quick-replies', kwargs=detail_kwargs)
        self.campaigns_url = reverse('prospect-campaigns', kwargs=detail_kwargs)

        # Make sure none of the important fields are None.
        prospect = self.george_campaign_prospect.prospect
        prospect.property_address = '123 fake st'
        prospect.property_city = 'seattle'
        prospect.property_state = 'wa'
        prospect.save()

    def __create_webhook(self):
        # Creates a zapier webhook and assigns to campaign.
        webhook = mommy.make(
            'sherpa.ZapierWebhook',
            campaign=self.george_campaign_prospect.campaign,
            webhook_url='http://www.example.com',
            status='active',
        )
        self.george_campaign_prospect.campaign.zapier_webhook = webhook
        self.george_campaign_prospect.campaign.save()

    def __push_to_zapier(self):
        # Send the request to push to zapier
        payload = {'campaign': self.george_campaign_prospect.campaign.id}
        response = self.george_client.post(self.push_to_zapier_url, payload)
        self.assertEqual(response.status_code, 200)
        self.george_campaign_prospect.prospect.refresh_from_db()
        self.assertTrue(self.george_campaign_prospect.prospect.pushed_to_zapier)

    def test_prospect_detail_requires_authentication(self):
        response = self.client.get(self.prospect_detail_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_prospect_detail(self):
        response = self.john_client.get(self.prospect_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('id'), self.george_prospect.id)

    def test_user_cant_get_others_prospect_detail(self):
        response = self.thomas_client.get(self.prospect_detail_url)
        self.assertEqual(response.status_code, 404)

    def test_user_cant_delete_prospect(self):
        response = self.john_client.delete(self.prospect_detail_url)
        self.assertEqual(response.status_code, 405)

    def test_can_search_by_name(self):
        url = self.prospect_search_url + '?search=doesnotexist'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)
        self.assertEqual(response.json().get('count'), 0)

        url = self.prospect_search_url + '?search=orda'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        url = self.prospect_search_url + '?search=dan'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 2)

        url = self.prospect_search_url + '?search=dan'
        response = self.thomas_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

        # Test if you can search for a prospect that has an empty `fullname` entry.
        response = self.thomas_client.get(url, {'search': 'stef'})
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

    def test_can_search_by_number(self):
        url = self.prospect_search_url + '?search=999'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

        url = self.prospect_search_url + '?search=509'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        url = self.prospect_search_url + '?search=206'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 2)

    def test_can_search_priority(self):
        priority_url = self.prospect_search_url + '?is_priority=true'
        self.george_prospect.is_priority = True
        self.george_prospect.save()

        # Verify that we can filter to priority prospects.
        response = self.john_client.get(priority_url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        # Verify that we can combine priority with name search.
        url = self.prospect_search_url + '?is_priority=true&search=bill'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

        # Verify when there are no priority prospects.
        self.george_prospect.is_priority = False
        self.george_prospect.save()
        response = self.john_client.get(priority_url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

    def test_can_search_qualified(self):
        qualified_url = self.prospect_search_url + '?is_qualified_lead=true'
        self.george_prospect.is_qualified_lead = True
        self.george_prospect.save()

        # Verify that we can filter to qualified prospects.
        response = self.john_client.get(qualified_url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        # Verify that we can combine qualified with name search.
        url = f'{qualified_url}&search=bill'
        response = self.john_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

        # Verify when there are no priority prospects.
        self.george_prospect.is_qualified_lead = False
        self.george_prospect.save()
        response = self.john_client.get(qualified_url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

    def test_does_not_have_relations_by_default(self):
        response = self.john_client.get(self.prospect_detail_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('campaigns'), None)
        self.assertEqual(response.json().get('campaignProspects'), None)

    def test_can_return_campaigns(self):
        url = self.prospect_detail_url + '?expand=campaigns'
        response = self.john_client.get(url)
        campaign_data = response.json().get('campaigns')
        self.assertNotEqual(response.json().get('campaigns'), None)

        for campaign in campaign_data:
            self.assertEqual(campaign.get('company'), self.company1.id)

    def test_can_return_campaign_prospects(self):
        url = self.prospect_detail_url + '?expand=campaign_prospects'
        response = self.john_client.get(url)
        cp_data = response.json().get('campaignProspects')
        self.assertNotEqual(cp_data, None)
        self.assertEqual(len(cp_data), self.george_prospect.campaignprospect_set.count())

    def test_cant_get_prospect_if_payment_required(self):
        self.company1.subscription_status = Company.SubscriptionStatus.PAUSED
        self.company1.save()
        response = self.john_client.get(self.prospect_list_url)
        self.assertEqual(response.status_code, 403)
        response = self.john_client.get(self.prospect_detail_url)
        self.assertEqual(response.status_code, 403)

        self.company1.subscription_status = Company.SubscriptionStatus.PAST_DUE
        self.company1.save()
        response = self.john_client.get(self.prospect_list_url)
        self.assertEqual(response.status_code, 403)
        response = self.john_client.get(self.prospect_detail_url)
        self.assertEqual(response.status_code, 403)

        self.company1.subscription_status = Company.SubscriptionStatus.ACTIVE
        self.company1.save()

    def test_can_toggle_qualified_lead(self):
        data = {'is_qualified_lead': True}
        url = self.prospect_detail_url
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('activities')), 2)
        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.OPEN,
        )
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.is_qualified_lead, True)
        self.assertEqual(self.george_prospect.qualified_lead_created_by, self.john_user)
        self.assertEqual(self.george_prospect.qualified_lead_dt is not None, True)

        # Owner should be verified because of qualification above.
        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.VERIFIED,
        )

        data = {'is_qualified_lead': False}
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('activities')), 1)
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.is_qualified_lead, False)
        self.assertEqual(self.george_prospect.qualified_lead_created_by, None)
        self.assertEqual(self.george_prospect.qualified_lead_dt, None)

        # Owner should still be verified because they became verified due to qualifications.
        self.assertEqual(
            self.george_prospect.owner_verified_status,
            self.george_prospect.OwnerVerifiedStatus.VERIFIED,
        )

    def test_other_user_cant_toggle_qualified_lead(self):
        data = {'is_qualified_lead': True}
        url = self.prospect_detail_url
        response = self.thomas_client.patch(url, data)
        self.assertEqual(response.status_code, 404)

    def test_can_toggle_is_priority(self):
        # Set priority on prospect and verify data updated correctly.
        data = {'is_priority': True}
        url = self.prospect_detail_url
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('activities')), 2)
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.is_priority, True)

        # Set priority to false and verify data updated correctly.
        data = {'is_priority': False}
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('activities')), 1)
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.is_priority, False)

    def test_other_user_cant_toggle_is_priority(self):
        data = {'is_priority': True}
        url = self.prospect_detail_url
        response = self.thomas_client.patch(url, data)
        self.assertEqual(response.status_code, 404)

    def test_can_toggle_owner_verified(self):
        data = {'owner_verified_status': 'verified'}
        url = self.prospect_detail_url
        self.george_campaign_prospect.prospect = self.thomas_prospect

        objects = [self.george_prospect, self.thomas_prospect]
        for obj in objects:
            obj.related_record_id = 'abcdef'
            obj.save(update_fields=['related_record_id'])
        self.george_campaign_prospect.save(update_fields=['prospect'])

        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.george_prospect.refresh_from_db()
        self.thomas_prospect.refresh_from_db()
        self.george_campaign_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.owner_verified_status, 'verified')
        self.assertEqual(self.thomas_prospect.owner_verified_status, 'unverified')
        self.assertEqual(self.thomas_prospect.wrong_number, True)
        self.assertEqual(self.thomas_prospect.lead_stage.lead_stage_title, 'Dead')
        self.assertEqual(self.george_campaign_prospect.skipped, True)
        data = {'owner_verified_status': 'open'}
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.owner_verified_status, 'open')

    def test_other_user_cant_toggle_owner_verified(self):
        data = {'owner_verified_status': 'open'}
        url = self.prospect_detail_url
        response = self.thomas_client.patch(url, data)
        self.assertEqual(response.status_code, 404)

    def test_can_toggle_do_not_call(self):
        data = {'do_not_call': True}
        url = self.prospect_detail_url
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.do_not_call, True)
        internal_dnc_list = InternalDNC.objects.filter(
            phone_raw=self.george_prospect.phone_raw,
            company=self.george_prospect.company,
        )
        self.assertTrue(len(internal_dnc_list) == 1)
        data = {'do_not_call': False}
        response = self.john_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.george_prospect.refresh_from_db()
        self.assertEqual(self.george_prospect.do_not_call, False)
        internal_dnc_list = InternalDNC.objects.filter(
            phone_raw=self.george_prospect.phone_raw,
            company=self.george_prospect.company,
        )
        self.assertTrue(len(internal_dnc_list) == 0)

    def test_other_user_cant_toggle_do_not_call(self):
        data = {'do_not_call': True}
        url = self.prospect_detail_url
        response = self.thomas_client.patch(url, data)
        self.assertEqual(response.status_code, 404)

    def test_toggle_wrong_number(self):
        # Setup george prospect to have an unread message.
        self.george_prospect.has_unread_sms = True
        self.george_prospect.save()
        self.assertFalse(self.george_prospect.wrong_number)

        payload = {'wrong_number': True}
        url = self.prospect_detail_url
        response = self.george_client.patch(url, payload)
        self.assertEqual(response.status_code, 200)

        # Verify all the data was updated accordingly.
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_prospect.wrong_number)
        self.assertFalse(self.george_prospect.has_unread_sms)

    def test_can_send_message(self):
        response = self.george_client.post(self.send_message_url)
        self.assertEqual(response.status_code, 400)

        payload = {'message': 'Hello, are you there?'}
        response = self.george_client.post(self.send_message_url, data=payload)
        self.assertEqual(response.status_code, 200)

    def test_jrstaff_cannot_send_message(self):
        response = self.jrstaff_client.post(self.send_message_url)
        self.assertEqual(response.status_code, 403)

    def test_market_empty_send_message(self):
        empty_market = mommy.make(
            'sherpa.Market',
            company=self.company1,
            parent_market=self.parent_market1,
        )
        self.george_campaign.market = empty_market
        self.george_campaign.save(update_fields=['market'])
        self.assertFalse(self.george_campaign.market.has_sufficient_numbers)

        payload = {'message': 'Hello, are you there?'}

        # Test should succeed as prospect has a valid number.
        response = self.george_client.post(self.send_message_url, data=payload)
        self.assertEqual(response.status_code, 200)

        # Test should fail as prospect has no valid number and market is empty.
        self.george_prospect.sherpa_phone_number_obj = None
        self.george_prospect.save(update_fields=['sherpa_phone_number_obj'])
        response = self.george_client.post(self.send_message_url, data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['detail'], 'No active numbers in market.')

    def test_cant_send_message_with_banned_word(self):
        bad_word = settings.BANNED_WORDS[5]
        payload = {'message': f'Hello {bad_word}, are you there?'}
        response = self.george_client.post(self.send_message_url, data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('message'), None)

    def test_can_send_prospect_to_zapier(self):
        self.__create_webhook()
        self.__push_to_zapier()

        # Can't push multiple times
        response2 = self.george_client.post(self.push_to_zapier_url)
        self.assertEqual(response2.status_code, 400)
        self.assertTrue('already pushed to Zapier' in response2.json().get('detail'))

        # Should have recorded a qualified & owner verified.
        first_activity = self.george_campaign_prospect.prospect.activity_set.first()
        last_activity = self.george_campaign_prospect.prospect.activity_set.last()
        self.assertEqual(first_activity.title, Activity.Title.OWNER_VERIFIED)
        self.assertEqual(last_activity.title, Activity.Title.ADDED_QUALIFIED)

    def test_cant_send_prospect_without_zapier(self):
        payload = {'campaign': self.george_campaign_prospect.campaign.id}
        response = self.george_client.post(self.push_to_zapier_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertTrue('does not have a zapier' in response.json().get('detail'))

    def test_can_send_qualified_to_zapier(self):
        prospect = self.george_campaign_prospect.prospect
        prospect.is_qualified_lead = True
        prospect.save()

        self.__create_webhook()
        self.__push_to_zapier()

    def test_cant_send_prospect_requires_campaign(self):
        response = self.george_client.post(self.push_to_zapier_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual('`campaign` is required in the request payload.',
                         response.json().get('detail'))

    def test_podio_data_has_skiptrace_data(self):
        # First we create a SkipTraceProperty record with some data
        _ = mommy.make(
            "sherpa.SkipTraceProperty",
            returned_phone_1=self.george_prospect.phone_raw,
            returned_email_1="address@test.com",
            prop=self.george_prop,
            # This looks clunky but its to make sure we dont happen to get a datetime that
            # might degenerate into a date without timestamp during conversion
            created=datetime.combine(datetime.now().date(), time(second=1)),
        )

        # Ensuring that getting the SkipTraceProperty from the prospect gets an appropriate record
        # That is, has a returned phone from the prospect and its property is from the same company
        related_stp = self.george_prospect.skiptrace
        self.assertEqual(
            related_stp.prop.company_id,
            self.george_prospect.company_id,
        )
        self.assertEqual(self.george_prospect.phone_raw, related_stp.returned_phone_1)

        # Export the podio prospect data and check that the skiptrace data is there
        prospect_data = PodioResource().export_resource(self.george_prospect)
        self.assertEqual(prospect_data["email_1"], "address@test.com")

        # The created field should be a datetime, which needs special handling to be converted
        # into a format Podio understands (separating date from timestamp)
        stp_created = related_stp.created
        self.assertIsInstance(stp_created, datetime)

        # We make sure skip_trace_data which is a datetime is properly converted to send to Podio.
        # For that we need a PodioFieldMapping that maps the field to an hypothetical Podio field.
        field_mapping = PodioFieldMapping(
            company=self.george_prospect.company,
            fields={
                '1': {
                    'value': ['skip_trace_date'],
                    'config': {
                        'delta': 13,
                        'label': 'Skip Traced Date',
                        'hidden': False,
                        'unique': False,
                        'mapping': None,
                        'visible': True,
                        'required': False,
                        'settings': {
                            'end': 'disabled',
                            'time': 'enabled',
                            'color': 'DCEBD8',
                            'calendar': False,
                        },
                        'field_type': 'date',
                        'description': None,
                        'default_value': None,
                        'hidden_create_view_edit': False,
                    },
                },
            },
        )
        data_to_sync = fetch_data_to_sync(
            field_mapping,
            {"prospect_id": self.george_prospect.pk},
        )
        start_time = f'{stp_created.hour:02d}:{stp_created.minute:02d}:{stp_created.second:02d}'
        self.assertEqual(
            data_to_sync["fields"]["1"],
            {
                'start_date': str(stp_created.date()),
                'start_time': start_time,
            },
        )

    def test_can_send_podio_email(self):
        # Prepare the campaign's data.
        prospect = self.george_campaign_prospect.prospect
        campaign = self.george_campaign_prospect.campaign
        campaign.podio_push_email_address = 'fake@asdf.com'
        campaign.save()

        # Send the request to email to podio.
        payload = {'campaign': campaign.id}
        response = self.george_client.post(self.email_to_podio_url, payload)
        self.assertEqual(response.status_code, 200)
        prospect.refresh_from_db()
        self.assertTrue(prospect.emailed_to_podio)
        self.assertEqual(prospect.lead_stage.lead_stage_title, 'Pushed to Podio')

        # Verify can't push multiple times.
        response2 = self.george_client.post(self.email_to_podio_url)
        self.assertEqual(response2.status_code, 400)
        self.assertTrue('already emailed to Podio' in response2.json().get('detail'))

        # Should have recorded a qualified & owner verified.
        first_activity = prospect.activity_set.first()
        last_activity = prospect.activity_set.last()
        self.assertEqual(first_activity.title, Activity.Title.OWNER_VERIFIED)
        self.assertEqual(last_activity.title, Activity.Title.ADDED_QUALIFIED)

    def test_send_to_podio_requires_email(self):
        payload = {'campaign': self.george_campaign_prospect.campaign.id}
        response = self.george_client.post(self.email_to_podio_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertTrue('does not have a podio email' in response.json().get('detail'))

    def test_send_to_podio_requires_campaign(self):
        response = self.george_client.post(self.email_to_podio_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual('`campaign` is required in the request payload.',
                         response.json().get('detail'))

    def test_can_search_text_no_lead_stage(self):
        url = self.prospect_search_url + '?search=' + self.george_prospect.first_name
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].get('firstName'), self.george_prospect.first_name)

    def test_can_search_name(self):
        # Search for just the last name.
        url = self.prospect_search_url + '?search=' + self.george_prospect.last_name
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].get('lastName'), self.george_prospect.last_name)

        # Search for just the full name.
        url = self.prospect_search_url + '?search=' + self.george_prospect.get_full_name()
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results2 = response.json().get('results')
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0].get('name'), self.george_prospect.get_full_name())

    def test_can_search_address(self):
        self.george_prospect.property_zip = 12345
        self.george_prospect.save(update_fields=['property_zip'])
        address_fields = {
            'property_address': 'propertyAddress',
            'property_city': 'propertyCity',
            'property_state': 'propertyState',
            'property_zip': 'propertyZip',
        }
        for field in address_fields:
            val = getattr(self.george_prospect, field)
            url = self.prospect_search_url + '?search=' + str(val)
            response = self.george_client.get(url)
            self.assertEqual(response.status_code, 200)
            results = response.json().get('results')
            self.assertEqual(len(results), 1)
            self.assertEqual(
                results[0].get(address_fields[field]),
                str(getattr(self.george_prospect, field)),
            )

    def test_search_phones(self):
        val = 2222222222
        self.george_prospect.phone_raw = val
        self.george_prospect.save(update_fields=['phone_raw'])
        url = self.prospect_search_url + '?search=' + str(val)
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

    def test_can_search_by_tag(self):
        tag = mommy.make(
            'PropertyTag',
            company=self.george_user.profile.company,
            name='test',
        )
        self.george_prospect.prop.tags.add(tag)
        url = self.prospect_search_url + f'?tag={tag.id}'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertTrue(len(results) > 0)
        self.assertEqual(results[0].get('id'), self.george_prospect.id)

    def test_can_search_by_owner_verified_status(self):
        # Verify search returns nothing if there's nothing matching 'owner_verified_status'.
        self.george_prospect.owner_verified_status = 'open'
        self.george_prospect.save(update_fields=['owner_verified_status'])
        url = self.prospect_search_url + '?verification=verified'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertFalse(len(results))

        # Verify can find matches by 'owner_verified_status'
        status = ['verified', 'unverified', 'open']
        for s in status:
            self.george_prospect.owner_verified_status = s
            self.george_prospect.save(update_fields=['owner_verified_status'])
            url = self.prospect_search_url + f'?verification={s}'
            response = self.george_client.get(url)
            self.assertEqual(response.status_code, 200)
            results = response.json().get('results')
            self.assertTrue(len(results) > 0)

    def test_search_can_get_multiple_matches(self):
        prospects = [self.george_prospect, self.george_prospect2]
        val = 12345
        for prospect in prospects:
            prospect.property_zip = 12345
            prospect.save(update_fields=['property_zip'])
        url = self.prospect_search_url + '?search=' + str(val)
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertEqual(len(results), 2)

    def test_search_by_lead_stage(self):
        # Prepare the data to be searched.
        lead_stage = LeadStage.objects.first()
        other_lead_stage = LeadStage.objects.last()
        self.george_prospect.lead_stage = lead_stage
        self.george_prospect2.lead_stage = other_lead_stage
        prospects = [self.george_prospect, self.george_prospect2]
        for prospect in prospects:
            prospect.save(update_fields=['lead_stage'])

        # Search for the lead stage and verify the response.
        url = self.prospect_search_url + '?lead_stage=' + str(lead_stage.id)
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)
        self.george_prospect2.lead_stage = lead_stage
        self.george_prospect2.save(update_fields=['lead_stage'])

        response2 = self.george_client.get(url)
        self.assertEqual(response2.status_code, 200)
        results2 = response2.json().get('results')
        self.assertEqual(len(results2), 2)

    def test_search_can_handle_blank_results(self):
        url = self.prospect_search_url + '?search=FakeName'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

    def test_search_special_cases(self):
        # Prepare the data to be searched.
        self.george_prospect.is_priority = True
        self.george_prospect2.is_qualified_lead = True
        prospects = [self.george_prospect, self.george_prospect2]
        for prospect in prospects:
            prospect.save(update_fields=['is_priority', 'is_qualified_lead'])
        priority_url = self.prospect_search_url + '?is_priority=true'

        # Verify the results.
        response = self.george_client.get(priority_url)
        self.assertEqual(response.status_code, 200)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get('id'), self.george_prospect.id)

        # Search by qualified lead and verify results.
        qualified_url = self.prospect_search_url + '?is_qualified_lead=true'
        response2 = self.george_client.get(qualified_url)
        self.assertEqual(response2.status_code, 200)
        results2 = response2.json().get('results')
        self.assertEqual(len(results2), 1)
        self.assertEqual(results2[0].get('id'), self.george_prospect2.id)

        # Search by priority and verify results.
        self.george_prospect2.is_priority = True
        self.george_prospect2.save(update_fields=['is_priority'])
        response3 = self.george_client.get(priority_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response3.json().get('results')), 2)

    def test_search_no_params_returns_all(self):
        url = self.prospect_search_url
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        count = Prospect.objects.filter(company=self.george_user.profile.company).count()
        self.assertEqual(len(response.json().get('results')), count)

    def test_search_asterisk_returns_all(self):
        url = self.prospect_search_url + '?search=*'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        count = Prospect.objects.filter(company=self.george_user.profile.company).count()
        self.assertEqual(len(response.json().get('results')), count)

    def test_search_with_number_field_excludes_non_number_fields(self):
        val = self.george_prospect.property_address
        self.assertTrue('123' in val)
        fields = ['first_name', 'last_name', 'property_city', 'property_state']
        for field in fields:
            setattr(self.george_prospect2, field, val)
        self.george_prospect2.save(update_fields=fields)

        for field in fields:
            self.assertEqual(getattr(self.george_prospect2, field), val)

        url = self.prospect_search_url + '?search=' + val
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 1)

        self.george_prospect2.property_zip = 12345
        self.george_prospect2.save(update_fields=['property_zip'])
        self.george_prospect3.phone_raw = 1231234567
        self.george_prospect3.save(update_fields=['phone_raw'])
        url = self.prospect_search_url + '?search=123'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 3)

    def test_search_test_pagination(self):
        # Make sure there's over 100 `Prospect` objects. Default is 100 per page.
        for i in range(101):
            mommy.make(
                'sherpa.Prospect',
                first_name='First',
                last_name='Last',
                company=self.company1,
                phone_raw='2062223333',
            )

        url = self.prospect_search_url
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        count = Prospect.objects.filter(company=self.george_user.profile.company).count()
        self.assertTrue(count > 100)
        self.assertEqual(len(response.json().get('results')), 100)
        # Test can change pagination.
        url += '?page_size=2'
        response = self.george_client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 2)

    """
    def test_es_search(self):
        response = self.george_client.get(self.prospect_es_search_url)
        results = response.json()
        size = len(results)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(results), 100)

        response = self.george_client.get(self.prospect_es_search_url, {'q': 'Mor'})
        results = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertNotEqual(len(results), size)

    def test_es_search_paging(self):
        page = {
            'page': 1,
            'page_size': 10,
        }
        response = self.george_client.get(self.prospect_es_search_url, page)
        results1 = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(results1), page['page_size'])

        page['page'] = 5
        response = self.george_client.get(self.prospect_es_search_url, page)
        results2 = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(results2), page['page_size'])

        self.assertNotEqual(results1, results2)
    """

    def test_can_mark_prospect_convo_as_read(self):
        # Prepare data to be marked as read.
        for _ in range(3):
            mommy.make('sherpa.SMSMessage', prospect=self.george_prospect, unread_by_recipient=True,
                       from_prospect=True)
        self.assertTrue(self.george_prospect.messages.filter(unread_by_recipient=True).count() > 0)
        self.assertFalse(self.george_prospect.has_unread_sms)

        # Verify that the messages were set to read.
        response = self.george_client.post(self.mark_as_read_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.george_prospect.messages.filter(unread_by_recipient=True).count(), 0)

    def test_can_get_quick_replies(self):
        mommy.make('sherpa.SMSPrefillText', sort_order=0, company=self.company1)
        mommy.make('sherpa.SMSPrefillText', sort_order=4, company=self.company1)
        mommy.make(
            'sherpa.SMSPrefillText',
            sort_order=3,
            company=self.company1,
            message="{FirstName}",
        )
        mommy.make('sherpa.SMSPrefillText', sort_order=1, company=self.company1)
        mommy.make('sherpa.SMSPrefillText', sort_order=2, company=self.company1)
        mommy.make('sherpa.SMSPrefillText', sort_order=0, company=self.company2)

        response = self.george_client.get(self.quick_replies_url)
        data = response.json()

        # Verify that the data is filtered to company.
        expected_count = self.company1.quick_replies.count()
        self.assertEqual(len(data), expected_count)

        # Verify ordering is correct and template gets filled in.
        current_order = 0
        found_first_name = False
        for prefill in data:
            instance = SMSPrefillText.objects.get(id=prefill.get('id'))
            self.assertTrue(instance.sort_order >= current_order)
            if self.george_prospect.first_name in prefill.get('messageFormatted'):
                found_first_name = True
            current_order += 1

        self.assertTrue(found_first_name)

    def test_can_get_prospect_campaigns(self):
        response = self.george_client.get(self.campaigns_url)
        self.assertTrue(len(response.json()) > 0)
        self.assertEqual(len(response.json()), self.george_prospect.campaign_qs.count())

    def test_anon_can_get_prospect_by_token(self):
        # Create a few messages for the prospect.
        prospect = self.george_prospect
        mommy.make(
            'SMSMessage',
            prospect=prospect,
            company=prospect.company,
            contact_number=prospect.full_number,
            from_prospect=False,
        )
        mommy.make(
            'SMSMessage',
            prospect=prospect,
            company=prospect.company,
            contact_number=prospect.full_number,
            from_prospect=True,
        )

        expected_length = prospect.messages.count()
        self.assertNotEqual(expected_length, 0)

        # Check that we can't get with id.
        # url1 = reverse('prospect-public', kwargs={'pk': prospect.id})
        # response1 = self.client.get(url1)
        # self.assertEqual(response1.status_code, 404)

        # Check that unauthenticated can get with token.
        url2 = reverse('prospect-public', kwargs={'pk': prospect.token})
        response2 = self.client.get(url2)
        self.assertEqual(response2.status_code, 200)
        self.assertEqual(len(response2.json().get('messages')), expected_length)

    def test_can_export_prospect_search(self):
        # Prepare some data to be tested.
        lead_stage = self.company1.leadstage_set.first()
        self.george_prospect.lead_stage = lead_stage
        self.george_prospect.is_qualified_lead = True
        self.george_prospect.save()

        self.george_prospect2.is_priority = True
        self.george_prospect2.save()
        self.george_prospect3.is_priority = True
        self.george_prospect3.save()

        # Download the full results.
        full_url = self.export_search_url
        full_response = self.george_client.get(full_url)
        download_id = full_response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = Prospect.objects.search(
            self.george_user,
            filters=download.filters,
        )
        resource = ProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        csv_count = len([data for data in csv_data])
        self.assertEqual(
            csv_count,
            self.company1.prospect_set.count(),
        )

        # Download only qualified.
        qualified_url = f'{self.export_search_url}?is_qualified_lead=true'
        qualified_response = self.george_client.get(qualified_url)
        download_id = qualified_response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = Prospect.objects.search(
            self.george_user,
            filters=download.filters,
        )
        resource = ProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        csv_count = len([data for data in csv_data])
        self.assertEqual(
            csv_count,
            self.company1.prospect_set.filter(is_qualified_lead=True).count(),
        )

        # Download only priority.
        priority_url = f'{self.export_search_url}?is_priority=true'
        priority_response = self.george_client.get(priority_url)
        download_id = priority_response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = Prospect.objects.search(
            self.george_user,
            filters=download.filters,
        )
        resource = ProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        csv_count = len([data for data in csv_data])
        self.assertEqual(
            csv_count,
            self.company1.prospect_set.filter(is_priority=True).count(),
        )

        # Download by lead stage.
        lead_stage_url = f'{self.export_search_url}?lead_stage={lead_stage.id}'
        lead_stage_response = self.george_client.get(lead_stage_url)
        download_id = lead_stage_response.json()['id']
        download = DownloadHistory.objects.get(uuid=download_id)
        queryset = Prospect.objects.search(
            self.george_user,
            filters=download.filters,
        )
        resource = ProspectResource().export(download, queryset)
        csv_data = csv.DictReader(io.StringIO(resource.csv))
        csv_count = len([data for data in csv_data])
        self.assertEqual(
            csv_count,
            self.company1.prospect_set.filter(lead_stage=lead_stage).count(),
        )

    def test_clone_prospect(self):
        prospect = self.george_prospect
        url = reverse('prospect-clone', kwargs={'pk': prospect.id})
        client = self.george_client

        mobile = '5095391234'
        property_address = '456 fake st.'
        payload = {
            'first_name': 'Nico',
            'property_address': property_address,
            'phone_raw': mobile,
        }

        # Test campaign required.
        response = client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('campaign')[0], 'This field is required.')
        payload['campaign'] = 0

        # Test invalid campaign id in payload.
        response = client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        payload['campaign'] = self.george_campaign.id

        # Test invalid phone numbers.
        existing = prospect.phone_raw
        invalid = 'aaaaaaaaaa'
        landline = '5093751234'

        # Test invalid phones.
        for phone_number in [existing, invalid, landline]:
            payload['phone_raw'] = phone_number
            response = client.post(url, payload)
            self.assertEqual(response.status_code, 400)
            self.assertNotEqual(response.json().get('phoneRaw'), None)

        # Now we can do the clone and verify the returned data.
        payload['phone_raw'] = mobile
        response = client.post(url, payload)
        self.assertEqual(response.status_code, 201)
        prospect_data = response.json().get('prospect')
        self.assertEqual(prospect_data.get('phoneRaw'), mobile)
        self.assertEqual(prospect_data.get('firstName'), 'Nico')
        self.assertEqual(prospect_data.get('propertyAddress'), property_address)

    def test_can_get_prospect_activity(self):
        # Create activity for some prospects.
        mommy.make('Activity', prospect=self.george_prospect)
        mommy.make('Activity', prospect=self.george_prospect)
        mommy.make('Activity', prospect=self.george_prospect2)

        # Check that the returned activity is correct for the prospect.
        url = reverse('prospect-activities', kwargs={'pk': self.george_prospect.id})
        response = self.george_client.get(url)
        expected = self.george_prospect.activity_set.count()
        self.assertNotEqual(expected, 0)
        self.assertEqual(len(response.json()), expected)

    def test_unauthorized_user_cant_add_tags(self):
        tag = mommy.make('ProspectTag', company=self.company1, is_custom=True, name='test')
        payload = {'tags': [tag.id]}
        response = self.client.patch(self.prospect_detail_url, payload)
        self.assertEqual(response.status_code, 401)

    def test_user_cant_add_tags_to_others_prospect(self):
        tag = mommy.make('ProspectTag', company=self.company1, is_custom=True, name='test')
        payload = {'tags': [tag.id]}
        response = self.thomas_client.patch(self.prospect_detail_url, payload)
        self.assertEqual(response.status_code, 404)

    def test_can_add_and_remove_tags(self):
        tag = mommy.make('PropertyTag', company=self.company1, is_custom=True, name='test')
        tag2 = mommy.make('PropertyTag', company=self.company1, is_custom=True, name='test2')

        # Add 2 tags.
        payload = {'tags': [tag.id, tag2.id]}
        response = self.george_client.patch(self.prospect_detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.george_prospect.prop.tags.count(), 2)

        # Remove 1 tag.
        payload = {'tags': [tag2.id]}
        response = self.george_client.patch(self.prospect_detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.george_prospect.prop.tags.count(), 1)

        # Remove ALL tags.
        payload = {'tags': []}
        response = self.george_client.patch(self.prospect_detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.george_prospect.prop.tags.count(), 0)

    def test_assign_number(self):
        url = reverse('prospect-assign-number', kwargs={'pk': self.george_prospect.pk})
        self.george_prospect.sherpa_phone_number_obj = None
        self.george_prospect.save(update_fields=['sherpa_phone_number_obj'])

        self.assertIsNone(self.george_prospect.sherpa_phone_number_obj)

        payload = {'force_assign': True}
        self.george_client.post(url, payload)
        self.george_prospect.refresh_from_db()
        self.assertIsNotNone(self.george_prospect.sherpa_phone_number_obj)

    def test_assign_number_without_market_numbers(self):
        url = reverse('prospect-assign-number', kwargs={'pk': self.george_prospect.pk})
        for phone_number in self.market1.phone_numbers.all():
            phone_number.delete()
        payload = {'force_assign': True}
        response = self.george_client.post(url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('detail'), None)

    def test_report_litigator(self):
        url = reverse('prospect-report', kwargs={'pk': self.george_prospect.pk})

        #  Assert that API will create a `LitigatorReportQueue` entry.
        response = self.george_client.post(url)
        self.assertEqual(response.status_code, 201)
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_prospect.do_not_call)
        self.assertTrue(self.george_prospect.is_blocked)
        queue = LitigatorReportQueue.objects.filter(prospect=self.george_prospect)
        self.assertTrue(queue.exists())
        queue = queue.first()
        self.assertEqual(queue.prospect.id, self.george_prospect.id)

        #  Assert `approve` action creates a `LitigatorList` entry.
        queue.approve(self.george_user)
        self.assertEqual(queue.status, LitigatorReportQueue.Status.APPROVED)
        self.assertTrue(LitigatorList.objects.filter(phone=self.george_prospect.phone_raw).exists())


class ProspectReminderAPITestCase(CampaignDataMixin, BaseAPITestCase):
    def setUp(self):
        super(ProspectReminderAPITestCase, self).setUp()
        prospect_kwargs = {'pk': self.george_prospect.id}
        self.set_reminder_url = reverse('prospect-set-reminder', kwargs=prospect_kwargs)
        self.remove_reminder_url = reverse('prospect-remove-reminder', kwargs=prospect_kwargs)

    def test_prospect_reminder_requires_payload(self):
        response = self.george_client.post(self.set_reminder_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json(),
            {'time': ['This field is required.'], 'agent': ['This field is required.']},
        )

    def test_can_set_prospect_reminder(self):
        payload = {
            'time': '2019-10-01T07:00:00Z',
            'agent': self.george_user.profile.id,
        }
        response = self.george_client.post(self.set_reminder_url, data=payload)
        self.assertEqual(response.status_code, 200)
        self.george_prospect.refresh_from_db()
        utc_datetime = parse('2019-10-01T07:00:00Z')
        self.assertEqual(self.george_prospect.reminder_date_utc, utc_datetime)
        self.assertEqual(self.george_prospect.reminder_agent, self.george_user.profile)
        self.assertTrue(self.george_prospect.has_reminder)

    def test_setting_reminder_clears_sent_status(self):
        self.george_prospect.reminder_email_sent = True
        self.george_prospect.save()

        # Verify that the reminder sent status is removed.
        payload = {
            'time': '2019-10-01T07:00:00Z',
            'agent': self.george_user.profile.id,
        }
        self.george_client.post(self.set_reminder_url, data=payload)
        self.george_prospect.refresh_from_db()
        self.assertFalse(self.george_prospect.reminder_email_sent)

    def test_can_remove_reminder(self):
        prospect = self.george_prospect
        agent_profile = self.george_user.profile

        # Set some fields to test for the prospect.
        prospect.reminder_date_utc = timezone.now()
        prospect.reminder_agent = agent_profile
        prospect.has_reminder = True
        prospect.save()

        # Verify that the data was set correctly.
        self.assertEqual(prospect.reminder_agent, agent_profile)
        self.assertNotEqual(prospect.reminder_date_utc, None)
        self.assertTrue(prospect.has_reminder)

        # Verify that the reminder can be removed.
        self.george_client.post(self.remove_reminder_url)
        prospect.refresh_from_db()
        self.assertEqual(prospect.reminder_agent, None)
        self.assertEqual(prospect.reminder_date_utc, None)
        self.assertFalse(prospect.has_reminder)

    def test_verify_bad_agent(self):
        payload = {
            'time': '2019-10-01T07:00:00Z',
            'agent': 1000,  # Obvious bad profile id.
        }
        response = self.george_client.post(self.set_reminder_url, data=payload)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('agent')[0], 'Agent does not exist.')


class ProspectModelTestCase(CampaignDataMixin, BaseTestCase):

    def setUp(self):
        super(ProspectModelTestCase, self).setUp()
        self.template = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message='Hello {FirstName} {CompanyName}',
            alternate_message='This is the alternative. {CompanyName}',
        )
        self.template2 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message='Hello! {FirstName} {CompanyName:1}',
            alternate_message='This is the alternative. {CompanyName:0}',
        )

    def test_auto_dead_creates_activity(self):
        self.george_prospect2.toggle_autodead(True)
        self.george_prospect2.refresh_from_db()
        activity = self.george_prospect2.activity_set.first()
        self.assertEqual(activity.title, Activity.Title.ADDED_AUTODEAD)
        self.assertEqual('Auto-dead added by system', activity.description)

    def test_can_remove_autodead(self):
        self.george_prospect2.toggle_autodead(False, user=self.george_user)
        self.george_prospect2.refresh_from_db()
        activity = self.george_prospect2.activity_set.first()
        self.assertEqual(activity.title, Activity.Title.REMOVED_AUTODEAD)
        self.assertTrue(self.george_user.get_full_name() in activity.description)

    def test_build_bulk_message(self):
        valid = self.george_prospect2.build_bulk_message(self.template)
        self.assertIn(self.george_prospect2.first_name, valid)
        self.assertIn(OPT_OUT_LANGUAGE, valid)
        self.george_prospect2.first_name = None
        self.george_prospect2.save()

    def test_build_bulk_message_with_specific_company(self):
        self.company1.outgoing_company_names.append('company_2_name')
        self.company1.save()

        valid = self.george_prospect2.build_bulk_message(self.template2)
        self.assertIn(self.company1.outgoing_company_names[1], valid)
        self.george_prospect2.first_name = None
        self.george_prospect2.save()
        valid = self.george_prospect2.build_bulk_message(self.template2)
        self.assertIn(self.company1.outgoing_company_names[0], valid)

    # def test_carrier_approved_template_message(self):
    #     msg = self.thomas_prospect2.build_bulk_message(
    #         self.carrier_approved_template,
    #         is_carrier_approved=True,
    #     )
    #     self.assertEqual(
    #         msg,
    #         f'Khal|ThomasTestCompany|{self.address_full}|1 Rd|ThomasTestUserName',
    #     )
    #     alternate_prospect = mommy.make(
    #         'sherpa.Prospect',
    #         company=self.company2,
    #         last_name='Empty',
    #     )
    #     msg = alternate_prospect.build_bulk_message(
    #         self.carrier_approved_template,
    #         is_carrier_approved=True,
    #     )
    #     self.assertEqual(msg, 'Alternate message|ThomasTestCompany|ThomasTestUserName')

    def test_can_get_verification_display(self):

        def check_owner_display(value, display):
            self.george_prospect.owner_verified_status = value
            self.george_prospect.save()

        check_owner_display(Prospect.OwnerVerifiedStatus.VERIFIED, 'owner')
        check_owner_display(Prospect.OwnerVerifiedStatus.UNVERIFIED, 'non-owner')
        check_owner_display(Prospect.OwnerVerifiedStatus.OPEN, '')
        check_owner_display('', '')

    def test_assign_new_number_when_released(self):
        prospect = self.george_prospect

        # Release the phone number.
        original_number = prospect.sherpa_phone_number_obj.phone
        original_sherpa_phone_number = PhoneNumber.objects.get(phone=original_number)
        original_sherpa_phone_number.release()
        original_sherpa_phone_number.refresh_from_db()
        prospect.refresh_from_db()
        self.assertEqual(original_sherpa_phone_number.status, PhoneNumber.Status.RELEASED)

        # Send a message a new number should be assigned.
        prospect.send_message('hello', self.george_user)
        prospect.refresh_from_db()
        self.assertNotEqual(original_sherpa_phone_number, prospect.sherpa_phone_number_obj)
        self.assertEqual(self.george_user.profile, prospect.agent)

    def test_toggle_priority_increments_campaign_stats(self):
        # Add prospect to another campaign so that they're in multiple.
        prospect = self.george_prospect
        self.george_campaign_prospect = mommy.make(
            'sherpa.CampaignProspect',
            prospect=prospect,
            campaign=self.george_campaign2,
        )
        campaign1_priority = self.george_campaign.campaign_stats.total_priority
        campaign2_priority = self.george_campaign2.campaign_stats.total_priority

        # Set the prospect to priority and verify that the campaigns were updated.
        self.george_prospect.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.george_campaign2.refresh_from_db()
        self.assertEqual(
            self.george_campaign.campaign_stats.total_priority,
            campaign1_priority + 1,
        )
        self.assertEqual(
            self.george_campaign2.campaign_stats.total_priority,
            campaign2_priority + 1,
        )

        # Add priority to another prospect and verify data.
        self.george_prospect2.toggle_is_priority(self.george_user, True)
        self.george_campaign.refresh_from_db()
        self.assertEqual(
            self.george_campaign.campaign_stats.total_priority,
            campaign1_priority + 2,
        )

        # And now remove the first prospect's priority
        self.george_prospect.toggle_is_priority(self.george_user, False)
        self.george_campaign.refresh_from_db()
        self.george_campaign2.refresh_from_db()
        self.assertEqual(
            self.george_campaign.campaign_stats.total_priority,
            campaign1_priority + 1,
        )
        self.assertEqual(
            self.george_campaign2.campaign_stats.total_priority,
            campaign2_priority,
        )

    def test_can_get_forwarding_number(self):
        self.assertEqual(self.george_prospect.call_forwarding_number, None)

        mommy.make('sherpa.CampaignProspect', prospect=self.george_prospect,
                   campaign=self.george_campaign3)

        active_campaign = Campaign.objects.filter(
            campaignprospect__prospect=self.george_prospect,
        ).first()

        # Verify that the market call forwarding number is picked up.
        active_campaign.market.call_forwarding_number = '2068887772'
        active_campaign.market.save()
        self.assertEqual(self.george_prospect.call_forwarding_number, '2068887772')

        # Verify that the campaign call forwarding number overrides market.
        active_campaign.call_forward_number = '2068887773'
        active_campaign.save()
        self.assertEqual(self.george_prospect.call_forwarding_number, '2068887773')

        # TODO: Need to verify that Agent Relay overrides everything else when it's added.

    def test_dnc_sets_messages_as_unread(self):
        # Create an unread message for the prospect.
        message = mommy.make(
            'sherpa.SMSMessage',
            prospect=self.george_prospect,
            from_prospect=True,
            unread_by_recipient=True,
        )

        # Verify that marking the prospect as dnc sets the message to read.
        self.george_prospect.toggle_do_not_call(self.george_user, True)
        message.refresh_from_db()
        self.assertFalse(message.unread_by_recipient)

    def test_creating_cloned_prospect_saves_related_record_id(self):
        self.assertNotEqual(self.george_prospect.related_record_id, '')
        self.assertNotEqual(self.george_prospect.related_record_id, None)
        new_prospect = mommy.make('sherpa.Prospect', cloned_from=self.george_prospect)
        self.assertEqual(new_prospect.related_record_id, self.george_prospect.related_record_id)

    def test_new_prospect_verify(self):
        full_name = 'Khal Drogo'
        property_address = {
            'street': '1 Rd',
            'city': 'Vaes Dothrak',
            'state': 'DS',
            'zip': '12345-6789',
        }
        mailing_address = {
            'street': '1 Rd',
            'city': 'Vaes Dothrak',
            'state': 'DS',
            'zip': '12345-6789',
        }

        self.assertFalse(
            self.thomas_prospect2.is_prospect_new(
                full_name,
                property_address,
                mailing_address,
            ),
        )

        # Test that a new name returns true.
        self.assertTrue(
            self.thomas_prospect2.is_prospect_new(
                'Petyr Baelish',
                property_address,
                mailing_address,
            ),
        )

        # Test that a new property address returns true
        self.assertTrue(
            self.thomas_prospect2.is_prospect_new(
                full_name,
                {
                    'street': '3 Rd',
                    'city': 'Vaes Dothrak',
                    'state': 'DS',
                    'zip': '12345-6789',
                },
                mailing_address,
            ),
        )

        # Test that a new mailing address returns true
        self.assertTrue(
            self.thomas_prospect2.is_prospect_new(
                full_name,
                property_address,
                {
                    'street': '3 Rd',
                    'city': 'Vaes Dothrak',
                    'state': 'DS',
                    'zip': '12345-6789',
                },
            ),
        )

    # DEPRECATED: Can remove after CA templates fully removed.
    # def test_require_carrier_approved_template(self):
    #     # Create phone type for the prospect.
    #     prospect = self.george_prospect
    #     phone_type_obj = mommy.make('PhoneType', phone=prospect.phone_raw)

    #     carrier_data = {
    #         'AT&T Wireless': False,
    #         'Cingular/2': False,
    #         'Cingular/2 Wireless': False,
    #         'BELLSOUTH TELECOMM': False,
    #         'SPRINT SPECTRUM L.P.': True,
    #         'Verizon Wireless': True,
    #         'T-Mobile': True,
    #         'SPRINT SPECTRUM L.P.': True,
    #     }

    #     # Verify that each carrier returns correct for whether it's valid or invalid.
    #     for carrier in carrier_data:
    #         expected = carrier_data[carrier]
    #         phone_type_obj.carrier = carrier
    #         phone_type_obj.save()

    #         if expected:
    #             self.assertFalse(prospect.is_carrier_template_verification_required())
    #         else:
    #             self.assertTrue(prospect.is_carrier_template_verification_required())

    def test_can_auto_tag(self):
        from properties.models import PropertyTag
        self.george_prospect.validated_property_vacant = 'Y'
        self.george_prospect.mailing_address = 'not property address'
        skip_trace = mommy.make('SkipTraceProperty', returned_judgment_date=datetime.now())
        self.george_prospect.save(update_fields=['validated_property_vacant', 'mailing_address'])
        self.george_prospect.apply_auto_tags(skip_trace)
        tags = [
            PropertyTag.objects.get(name='Judgement', company=self.george_prospect.company),
            PropertyTag.objects.get(name='Vacant', company=self.george_prospect.company),
            PropertyTag.objects.get(name='Absentee', company=self.george_prospect.company),
        ]

        for tag in tags:
            self.assertEqual(tag.prospect_count, 1)

    def test_check_prospect_wrong_number(self):
        self.assertFalse(self.george_prospect.mark_as_wrong_number)

        # Now let's create a few wrong numbers for the number
        for _ in range(2):
            mommy.make(
                'sherpa.Prospect',
                phone_raw=self.george_prospect.phone_raw,
                wrong_number=True,
                first_name=self.george_prospect.first_name,
            )
        self.assertTrue(self.george_prospect.mark_as_wrong_number)

    def test_can_create_prospects_from_phones(self):
        # This is testing creating Prospects using UploadProspect. Will test creating from skip
        # trace separately.
        prop = mommy.make('Property')
        data = {'first_name': 'First', 'last_name': 'Last', 'email': 'email@test.com', 'prop': prop}
        phones = ['2222222222', '3333333333', '4444444444']
        upload = mommy.make('UploadProspects', company=self.company1)

        Prospect.objects.create_from_phones(phones, data, upload=upload, prop=prop)

        for phone in phones:
            self.assertTrue(Prospect.objects.filter(phone_raw=phone).exists())


class ProspectMessagingAPITestCase(CampaignDataMixin, BaseAPITestCase):

    def setUp(self):
        super(ProspectMessagingAPITestCase, self).setUp()
        self.sms_message = mommy.make(
            'sherpa.SMSMessage',
            prospect=self.george_prospect,
            company=self.company1,
            contact_number=self.george_prospect.full_number,
        )
        self.prospect_detail_url = reverse(
            'prospect-detail',
            kwargs={'pk': self.george_prospect.id},
        )
        self.george_prospect_message_url = self.prospect_detail_url + 'messages/'

    def test_can_get_prospect_messages(self):
        response = self.john_client.get(self.george_prospect_message_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)

    def test_cant_get_other_prospect_messages(self):
        response = self.thomas_client.get(self.george_prospect_message_url)
        self.assertEqual(response.status_code, 404)


class ProspectNotesAPITestCase(CampaignDataMixin, BaseAPITestCase):

    prospect_notes_list_url = reverse('prospectnote-list')

    def setUp(self):
        super(ProspectNotesAPITestCase, self).setUp()
        self.note1 = mommy.make('sherpa.Note', prospect=self.george_prospect,
                                created_by=self.george_user)
        self.note2 = mommy.make('sherpa.Note', prospect=self.george_prospect,
                                created_by=self.george_user)
        self.note3 = mommy.make('sherpa.Note', prospect=self.george_prospect2,
                                created_by=self.john_user)
        prospect_id = self.george_prospect.id
        self.george_prospect_notes_url = self.prospect_notes_list_url + \
            f'?prospect={prospect_id}'
        self.note1_detail_url = reverse('prospectnote-detail', kwargs={'pk': self.note1.id})

    def test_user_can_get_their_prospect_notes(self):
        response = self.john_client.get(self.prospect_notes_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 3)

    def test_user_can_filter_prospect_notes(self):
        response = self.john_client.get(self.george_prospect_notes_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 2)
        results = response.json().get('results')
        for note_data in results:
            self.assertEqual(note_data.get('prospect'), self.george_prospect.id)

    def test_user_cant_get_other_prospect_notes(self):
        response = self.thomas_client.get(self.george_prospect_notes_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json().get('results')), 0)

    def test_can_create_prospect_note(self):
        payload = {'text': 'this is a test', 'prospect': self.george_prospect2.id}
        response = self.george_client.post(self.prospect_notes_list_url, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get('createdBy').get('id'), self.george_user.id)

    def test_create_note_creates_activity(self):
        prospect = self.george_prospect2
        initial_count = prospect.activity_set.count()
        payload = {'text': 'is activity created?', 'prospect': prospect.id}
        self.george_client.post(self.prospect_notes_list_url, payload)

        self.assertEqual(prospect.activity_set.count(), initial_count + 1)
        self.assertEqual(prospect.activity_set.first().title, Activity.Title.CREATED_NOTE)

    def test_user_can_edit_prospect_note(self):
        updated_text = 'new text'
        payload = {'text': updated_text}
        response = self.john_client.patch(self.note1_detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('text'), updated_text)

    def test_user_cant_edit_other_prospect_notes(self):
        payload = {'text': 'new text'}
        response = self.thomas_client.patch(self.note1_detail_url, payload)
        self.assertEqual(response.status_code, 404)

    def test_user_can_delete_their_prospect_note(self):
        response = self.john_client.delete(self.note1_detail_url)
        self.assertEqual(response.status_code, 204)

    def test_user_cant_delete_other_prospect_note(self):
        response = self.thomas_client.delete(self.note1_detail_url)
        self.assertEqual(response.status_code, 404)

    def test_created_by_is_expanded(self):
        url = self.prospect_notes_list_url
        response = self.john_client.get(url)
        for note_data in response.json().get('results'):
            self.assertEqual(type(note_data.get('createdBy')), dict)


class ProspectTagAPITestCase(CampaignDataMixin, BaseAPITestCase):
    prospect_tag_list_url = reverse('prospecttag-list')

    def setUp(self):
        super(ProspectTagAPITestCase, self).setUp()
        self.george_tag = mommy.make('ProspectTag', company=self.company1, is_custom=True)
        self.george_tag2 = mommy.make('ProspectTag', company=self.company1, is_custom=True)
        self.george_system_tag = mommy.make('ProspectTag', company=self.company1)
        self.thomas_tag = mommy.make('ProspectTag', company=self.company2, is_custom=True)
        detail_kwargs = {'pk': self.george_tag.id}
        self.prospect_tag_detail_url = reverse('prospecttag-detail', kwargs=detail_kwargs)

    def test_cant_get_tags_if_not_authenticated(self):
        response = self.client.get(self.prospect_tag_list_url)
        self.assertEqual(response.status_code, 401)

    def test_can_get_companies_tags(self):
        george_tag_count = self.company1.prospecttag_set.count()
        response = self.george_client.get(self.prospect_tag_list_url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('count'), george_tag_count)

    def test_cant_delete_tags_if_not_authenticated(self):
        response = self.client.delete(self.prospect_tag_detail_url)
        self.assertEqual(response.status_code, 401)

    def test_user_cant_delete_others_tags(self):
        response = self.thomas_client.delete(self.prospect_tag_detail_url)
        self.assertEqual(response.status_code, 404)

    def test_non_admin_cant_delete_tags(self):
        response = self.jrstaff_client.delete(self.prospect_tag_detail_url)
        self.assertEqual(response.status_code, 403)

    def test_can_delete_tag(self):
        pk = self.george_tag.pk
        self.assertTrue(ProspectTag.objects.filter(pk=pk).exists())
        response = self.george_client.delete(self.prospect_tag_detail_url)
        self.assertEqual(response.status_code, 204)
        self.assertFalse(ProspectTag.objects.filter(pk=pk).exists())

    def test_cant_delete_system_tag(self):
        url = reverse('prospecttag-detail', kwargs={'pk': self.george_system_tag.pk})
        response = self.george_client.delete(url)
        self.assertEqual(response.status_code, 403)

    def test_unauthenticated_user_cant_create_tag(self):
        payload = {'name': 'test'}
        response = self.client.post(self.prospect_tag_list_url, payload)
        self.assertEqual(response.status_code, 401)

    def test_non_admin_cant_create_tag(self):
        payload = {'name': 'test'}
        response = self.jrstaff_client.post(self.prospect_tag_list_url, payload)
        self.assertEqual(response.status_code, 403)

    def test_can_create_tag(self):
        payload = {'name': 'test'}
        response = self.george_client.post(self.prospect_tag_list_url, payload)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json().get('name'), 'test')

        # Verify it assigned correct company & defaulted isCustom to True.
        self.assertEqual(response.json().get('company'), self.company1.id)
        self.assertTrue(response.json().get('isCustom'))

    def test_unauthenticated_user_cant_update_tag(self):
        payload = {'name': 'test'}
        response = self.client.patch(self.prospect_tag_detail_url, payload)
        self.assertEqual(response.status_code, 401)

    def test_non_admin_cant_update_tag(self):
        payload = {'name': 'test'}
        response = self.jrstaff_client.patch(self.prospect_tag_detail_url, payload)
        self.assertEqual(response.status_code, 403)

    def test_cant_update_system_tag(self):
        payload = {'name': 'test'}
        url = reverse('prospecttag-detail', kwargs={'pk': self.george_system_tag.pk})
        response = self.george_client.patch(url, payload)
        self.assertEqual(response.status_code, 403)

    def test_can_update_tag(self):
        self.assertNotEqual(self.george_tag.name, 'test42')
        payload = {'name': 'test42'}
        response = self.george_client.patch(self.prospect_tag_detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json().get('name'), 'test42')


class CampaignBatchSkipTestCase(CampaignDataMixin, BaseTestCase):
    """
    Tests related to if a campaign prospect should be skipped during batch send.
    """
    def setUp(self):
        super(CampaignBatchSkipTestCase, self).setUp()
        self.stats_batch = mommy.make('sherpa.StatsBatch', campaign=self.george_campaign)
        self.george_campaign_prospect.stats_batch = self.stats_batch
        self.george_campaign_prospect.save()

    def create_receipt(self):
        mommy.make(
            'sherpa.ReceiptSmsDirect',
            company=self.company2,
            campaign=self.george_campaign,
            phone_raw=self.george_prospect.phone_raw,
        )

    def assertSkipReason(self, skip_reason):
        self.assertTrue(self.george_campaign_prospect.skipped)
        self.assertEqual(self.george_campaign_prospect.skip_reason, skip_reason)

    def assertNotSkipped(self):
        self.assertFalse(self.george_campaign_prospect.skipped)
        self.assertEqual(self.george_campaign_prospect.skip_reason, "")

    def test_force_skip(self):
        self.create_receipt()
        self.george_campaign_prospect.check_skip(force_skip=True)
        self.assertSkipReason(CampaignProspect.SkipReason.FORCED)

    def test_cp_skipped_threshold(self):
        self.create_receipt()
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.THRESHOLD_MESSAGE)

    def test_not_skipped_exempt_threshold(self):
        self.company1.threshold_exempt = True
        self.company1.save()
        self.create_receipt()

        self.george_campaign_prospect.check_skip()
        self.assertNotSkipped()

    def test_has_responded_to_message(self):
        self.george_prospect.has_responded_via_sms = 'yes'
        self.george_prospect.save()
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.HAS_RESPONDED)

    def test_campaign_skip_prospects_who_messaged(self):
        self.george_campaign.skip_prospects_who_messaged = False
        self.george_campaign.save()
        self.george_prospect.has_responded_via_sms = 'yes'
        self.george_prospect.save()
        self.george_campaign_prospect.check_skip()
        self.assertFalse(self.george_campaign_prospect.skipped)

    def test_cp_skipped_public_dnc(self):
        mommy.make('sherpa.InternalDNC', phone_raw=self.george_prospect.phone_raw,
                   company=self.company1)
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.PUBLIC_DNC)

    def test_cp_skipped_verizon(self):
        mommy.make(
            'sherpa.PhoneType',
            phone=self.george_prospect.phone_raw,
            company=self.company1,
            carrier='DBA Verizon',
        )
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.VERIZON)

    def tset_cp_skipped_opted_out(self):
        self.george_prospect.opted_out = True
        self.george_prospect.save()
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.OPTED_OUT)

    def test_cp_skipped_company_dnc(self):
        self.george_prospect.do_not_call = True
        self.george_prospect.save()
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.COMPANY_DNC)

    def test_cp_skipped_litigator(self):
        mommy.make('sherpa.LitigatorList', phone=self.george_prospect.phone_raw)
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.LITIGATOR)

    def test_cp_skipped_has_sms_receipt(self):
        receipt = mommy.make(
            'sherpa.ReceiptSmsDirect',
            company=self.company1,
            campaign=self.george_campaign,
            phone_raw=self.george_prospect.phone_raw,
        )
        ago = timezone.now() - timedelta(days=10)
        receipt.sent_date = ago
        receipt.save()
        self.george_campaign_prospect.check_skip()
        self.assertSkipReason(CampaignProspect.SkipReason.SMS_RECEIPT)

    # DEPRECATED: Can remove after CA templates fully removed.
    # def test_cp_skipped_outgoing_not_set(self):
    #     # Setup data so that the prospect is skipped.
    #     campaign_prospect = self.george_campaign_prospect
    #     phone = campaign_prospect.prospect.phone_raw
    #     mommy.make('sherpa.PhoneType', phone=phone, carrier='AT&T')
    #     company = campaign_prospect.prospect.company
    #     company.send_carrier_approved_templates = True
    #     company.outgoing_company_names = []
    #     company.save()

    #     # Verify that the prospect is skipped because company does not have outgoing data.
    #     campaign_prospect.check_skip()
    #     self.assertSkipReason(CampaignProspect.SkipReason.OUTGOING_NOT_SET)

    def test_cp_not_skipped(self):
        self.assertNotSkipped()


class ProspectRelayAPITestCase(CampaignDataMixin, BaseAPITestCase):
    list_url = reverse('prospectrelay-list')

    def setUp(self):
        super(ProspectRelayAPITestCase, self).setUp()
        self.relay_number1 = mommy.make('prospects.RelayNumber', phone='2061112222')
        self.relay_number2 = mommy.make('prospects.RelayNumber', phone='2061113333')
        self.relay_number3 = mommy.make('prospects.RelayNumber', phone='2061114444')

        self.relay1 = mommy.make(
            'prospects.ProspectRelay',
            prospect=self.george_prospect,
            agent_profile=self.george_user.profile,
        )
        self.relay2 = mommy.make(
            'prospects.ProspectRelay',
            prospect=self.george_prospect2,
            agent_profile=self.george_user.profile,
        )
        self.relay3 = mommy.make(
            'prospects.ProspectRelay',
            prospect=self.george_prospect2,
            agent_profile=self.john_user.profile,
        )
        self.relay4 = mommy.make(
            'prospects.ProspectRelay',
            prospect=self.thomas_prospect,
            agent_profile=self.thomas_user.profile,
        )

        self.disconnect_url = reverse('prospectrelay-disconnect', kwargs={'pk': self.relay1.id})
        self.connect_url = reverse('prospectrelay-connect')

    def test_prospect_relay_requires_auth(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 401)

    def test_can_get_prospect_relay_data_for_company(self):
        response = self.george_client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        for data in response.json():
            self.assertEqual(data.get('agentProfile').get('company'), self.company1.id)

    def test_can_disconnect_a_prospect_relay(self):
        response = self.george_client.post(self.disconnect_url)
        self.assertEqual(response.status_code, 200)

    def test_cant_disconnect_a_prospect_outside_company(self):
        response = self.thomas_client.post(self.disconnect_url)
        self.assertEqual(response.status_code, 404)

    def test_cant_connect_prospect_outside_company(self):
        payload = {
            "agentProfile": self.thomas_user.profile.id,
            "prospect": self.george_prospect.id,
        }
        response = self.george_client.post(self.connect_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertNotEqual(response.json().get('detail'), None)

    def test_can_connect_a_prospect_relay(self):
        profile = self.george_user.profile
        prospect = self.george_prospect3
        self.assertEqual(prospect.prospectrelay_set.first(), None)

        # Send the connect request.
        payload = {
            "agentProfile": profile.id,
            "prospect": prospect.id,
        }
        response = self.george_client.post(self.connect_url, payload)
        self.assertEqual(response.status_code, 200)

        # Verify that the prospect is connected.
        relay = prospect.prospectrelay_set.first()
        self.assertEqual(relay.agent_profile, profile)
        self.assertEqual(relay.prospect, prospect)


class ProspectUtilTestCase(CompanyOneMixin, NoDataBaseTestCase):
    empty_search_params = {
        'lead_stage': '',
        'tag': '',
        'is_priority': 'false',
        'is_qualified_lead': 'false',
        'search': '',
    }

    def setUp(self):
        super(ProspectUtilTestCase, self).setUp()
        sherpa_phone_number = mommy.make('sherpa.PhoneNumber', company=self.company1)
        self.prospect = mommy.make('sherpa.Prospect', sherpa_phone_number_obj=sherpa_phone_number)

    def test_is_empty_search(self):
        self.assertTrue(is_empty_search(self.empty_search_params))
        non_empty = self.empty_search_params
        non_empty['search'] = 'something'
        self.assertFalse(is_empty_search(non_empty))

    def test_record_phone_number_opt_outs(self):
        prospect = self.prospect
        record_phone_number_opt_outs(prospect.phone_raw, prospect.sherpa_phone_number_obj.phone)

        prospect.refresh_from_db()
        self.assertEqual(prospect.sherpa_phone_number_obj.total_opt_outs, 1)
        self.assertTrue(prospect.opted_out)


"""
class PhoneTypeModelTestCase(CampaignDataMixin, BaseTestCase):
    def setUp(self):
        super().setUp()
        self.phone = mommy.make(
            'sherpa.PhoneType',
            company=self.company1,
            campaign=self.george_campaign,
            phone='5555555505',
        )

    def test_carrier_check(self):
        today = datetime.now().date()
        other_date = date(2020, 1, 1)
        self.assertEqual(today, self.phone.last_lookup_date)
        self.assertFalse(self.phone.should_lookup_carrier)

        self.phone.last_carrier_lookup = other_date
        self.phone.save()
        self.assertEqual(other_date, self.phone.last_lookup_date)
        self.assertTrue(self.phone.should_lookup_carrier)
"""
