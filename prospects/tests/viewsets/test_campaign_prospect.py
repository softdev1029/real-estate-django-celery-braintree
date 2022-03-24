from dateutil.parser import parse
from model_mommy import mommy

from django.urls import reverse

from campaigns.tests import CampaignDataMixin
from sherpa.models import (
    CampaignProspect,
    LeadStage,
)
from sherpa.tests import BaseAPITestCase


class CampaignProspectAPITestCase(CampaignDataMixin, BaseAPITestCase):
    list_url = reverse('campaignprospect-list')
    cp_unread_url = reverse('campaignprospect-unread')

    def setUp(self):
        super(CampaignProspectAPITestCase, self).setUp()
        george_kwargs = {'pk': self.george_campaign_prospect.id}
        self.george_batch_send_url = reverse('campaignprospect-batch-send', kwargs=george_kwargs)
        self.detail_url = reverse('campaignprospect-detail', kwargs=george_kwargs)
        thomas_kwargs = {'pk': self.thomas_campaign_prospect.id}
        self.thomas_batch_send_url = reverse('campaignprospect-batch-send', kwargs=thomas_kwargs)

    def test_can_send_batch_text(self):
        response = self.george_client.post(self.george_batch_send_url)
        # Sometimes can fail due to timezone...
        self.assertTrue(response.status_code in [200, 400])
        if response.status_code == 200:
            prospect = self.george_prospect
            prospect.refresh_from_db()
            self.assertEqual(prospect.agent, self.george_user.profile)

    def test_cant_batch_send_when_over_limit(self):
        market = self.george_campaign_prospect.campaign.market
        market.total_intial_sms_sent_today_count = market.total_initial_send_sms_daily_limit + 1
        market.save(update_fields=['total_intial_sms_sent_today_count'])
        response = self.george_client.post(self.george_batch_send_url)
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json().get('detail'), "Daily limit has been reached")

    def test_jrstaff_cannot_send_batch_text(self):
        response = self.jrstaff_client.post(self.george_batch_send_url)
        self.assertTrue(response.status_code == 403)

    def test_batch_text_requires_sms_template(self):
        self.george_campaign.sms_template = None
        self.george_campaign.save()
        response = self.george_client.post(self.george_batch_send_url)
        self.assertEqual(response.status_code, 400)

    def test_batch_send_mark_as_dnc(self):
        initial_skip_count = self.george_campaign.campaign_stats.total_skipped
        payload = {'action': 'dnc'}
        response = self.george_client.post(self.george_batch_send_url, payload)
        self.assertEqual(response.status_code, 200)

        # Verify the data has been updated correctly.
        self.george_campaign.refresh_from_db()
        self.george_campaign_prospect.refresh_from_db()
        self.george_campaign_prospect.prospect.refresh_from_db()

        self.assertTrue(self.george_campaign_prospect.skipped)
        self.assertTrue(self.george_campaign_prospect.prospect.do_not_call)
        self.assertEqual(
            self.george_campaign.campaign_stats.total_skipped,
            initial_skip_count + 1,
        )

    # DEPRECATED: Can remove after CA templates fully removed.
    # def test_batch_text_skip_verified_template_required(self):
    #     url = reverse(
    #         'campaignprospect-batch-send',
    #         kwargs={'pk': self.george_campaign_prospect4.id},
    #     )
    #     response = self.george_client.post(url)
    #     self.assertEqual(response.status_code, 200)
    #     self.george_campaign_prospect4.refresh_from_db()
    #     self.assertTrue(self.george_campaign_prospect4.skipped)
    #     self.assertEqual(
    #         self.george_campaign_prospect4.skip_reason,
    #         self.george_campaign_prospect4.SkipReason.ATT,
    #     )

    def test_batch_text_skip_wrong_number(self):
        sms_template = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company2,
            alternate_message='this is the alternate {CompanyName}',
            message='hello {FirstName} {CompanyName}',
        )
        campaign = mommy.make(
            'sherpa.Campaign',
            name='Wrong Number Company',
            company=self.company2,
            market=self.company2.market_set.first(),
            sms_template=sms_template,
        )
        prospect = mommy.make(
            'sherpa.Prospect',
            company=self.company2,
            first_name='Link',
            last_name='Hero',
            property_address='1 Deku Tree',
            property_city='Hyrule',
            property_state='Hyrule',
            property_zip='12345-6789',
            phone_raw='3333333339',
            wrong_number=True,
        )
        campaign_prospect = mommy.make(
            'sherpa.CampaignProspect',
            prospect=prospect,
            campaign=campaign,
        )
        url = reverse('campaignprospect-batch-send', kwargs={'pk': campaign_prospect.id})
        response = self.thomas_client.post(url)
        self.assertEqual(response.status_code, 200)
        campaign_prospect.refresh_from_db()
        self.assertTrue(campaign_prospect.skipped)
        self.assertEqual(
            campaign_prospect.skip_reason,
            campaign_prospect.SkipReason.WRONG_NUMBER,
        )

    def test_send_requires_authentication(self):
        payload = {'smsTemplateId': 1}
        response = self.client.post(self.george_batch_send_url, data=payload)
        self.assertEqual(response.status_code, 401)

    def test_can_skip_campaign_prospect(self):
        response = self.george_client.post(self.george_batch_send_url, data={'action': 'skip'})
        self.assertEqual(response.status_code, 200)

        cp = self.george_campaign_prospect
        active_sb = cp.campaign.statsbatch_set.first()

        # Verify all the data has been updated.
        cp.refresh_from_db()
        self.assertEqual(active_sb.total_skipped, 1)
        self.assertEqual(active_sb.skipped_force, 1)
        self.assertEqual(cp.skip_reason, CampaignProspect.SkipReason.FORCED)
        self.assertTrue(cp.skipped)

    def test_can_fetch_campaign_prospects(self):
        response = self.george_client.get(self.list_url)
        results = response.json().get('results')
        self.assertEqual(
            len(results),
            CampaignProspect.objects.filter(prospect__company=self.company1).count(),
        )

    def test_can_expand_campaign(self):
        url = f'{self.list_url}?expand=campaign'
        response = self.george_client.get(url)
        results = response.json().get('results')

        self.assertTrue(len(results) > 0)
        for campaign_data in results:
            self.assertEqual(type(campaign_data.get('campaign')), dict)

    def test_can_filter_by_campaign(self):
        url = self.list_url + f'?campaign={self.george_campaign.id}'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(
            len(results),
            CampaignProspect.objects.filter(campaign=self.george_campaign).count(),
        )

        for cp in results:
            self.assertEqual(cp.get('campaign').get('id'), self.george_campaign.id)

    def test_can_filter_cp_by_lead_stage(self):
        lead_stage = self.company1.leadstage_set.all()[5]
        self.george_prospect.lead_stage = self.company1.leadstage_set.all()[4]
        self.george_prospect.save()
        self.george_prospect4.lead_stage = lead_stage
        self.george_prospect4.save()
        url = self.list_url + f'?lead_stage={lead_stage.id}'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(
            len(results),
            self.company1.prospect_set.filter(lead_stage=lead_stage).count(),
        )
        for prospect_data in results:
            self.assertEqual(prospect_data.get('prospect').get('leadStage'), lead_stage.id)

    def test_can_filter_cp_by_priority_unread(self):
        url = self.list_url + '?is_priority_unread=true'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

        # Add priority to the prospect
        self.george_prospect2.is_priority = True
        self.george_prospect2.save()
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        # Also add has unread to the prospect
        self.george_prospect2.has_unread_sms = True
        self.george_prospect2.save()
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        # Now remove priority testing just has unread
        self.george_prospect2.is_priority = False
        self.george_prospect2.save()
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 1)

        # Verify other users don't have access.
        response = self.thomas_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

    def test_can_filter_on_qualified(self):
        url = self.list_url + '?is_qualified_lead=true'
        response = self.george_client.get(url)
        results = response.json().get('results')
        self.assertEqual(len(results), 0)

        self.george_prospect4.is_qualified_lead = True
        self.george_prospect4.save()

        response2 = self.george_client.get(url)
        george_results = response2.json().get('results')
        self.assertEqual(len(george_results), 1)

        response3 = self.thomas_client.get(url)
        thomas_results = response3.json().get('results')
        self.assertEqual(len(thomas_results), 0)

    def test_campaign_prospects_return_display_message(self):
        prospects = self.company1.prospect_set.all()
        prospect1 = prospects[0]
        prospect2 = prospects[1]
        mommy.make('sherpa.SMSMessage', prospect=prospect1, message='first', from_prospect=True)
        msg1 = mommy.make('sherpa.SMSMessage', prospect=prospect1, message='second',
                          from_prospect=True)
        mommy.make('sherpa.SMSMessage', prospect=prospect2, message='third', from_prospect=False)
        msg2 = mommy.make('sherpa.SMSMessage', prospect=prospect2, message='fourth',
                          from_prospect=True)

        prospect1 = msg1.prospect
        prospect1.last_sms_received_utc = msg1.dt
        prospect1.save(update_fields=['last_sms_received_utc'])
        prospect2 = msg2.prospect
        prospect2.last_sms_received_utc = msg2.dt
        prospect2.save(update_fields=['last_sms_received_utc'])

        response = self.george_client.get(self.list_url)
        results = response.json().get('results')
        message1 = results[0].get('prospect').get('displayMessage')  # fourth
        message2 = results[1].get('prospect').get('displayMessage')  # third

        self.assertEqual(message2.get('message'), msg1.message)
        self.assertEqual(parse(message2.get('dt')), msg1.dt)
        self.assertEqual(message1.get('message'), msg2.message)
        self.assertEqual(parse(message1.get('dt')), msg2.dt)

    def test_can_get_unread_campaign_prospects(self):
        # Verify that no unreads come back by default.
        response = self.george_client.get(self.cp_unread_url)
        self.assertEqual(len(response.json().get('results')), 0)

        # Set campaign prospects to have unread messages in unread campaign.
        george_campaign2_prospect3 = mommy.make(
            'sherpa.CampaignProspect',
            prospect=self.george_prospect3,
            campaign=self.george_campaign2,
        )
        campaign_prospects = [
            self.george_campaign_prospect,
            self.george_campaign_prospect2,
            # We have a prospect have unread messages on two campaigns, should get counted once
            self.george_campaign_prospect3,
            george_campaign2_prospect3,
        ]

        # Update campaigns and prospects to have unread sms
        for cp in campaign_prospects:
            cp.prospect.has_unread_sms = True
            cp.prospect.save()

            cp.campaign.has_unread_sms = True
            cp.campaign.save()

        # Test that archived shows up still
        self.george_campaign2.is_archived = True
        self.george_campaign2.save()

        # Verify that users without access don't receive unread.
        staff_response = self.staff_client.get(self.cp_unread_url).json()
        self.assertEqual(len(staff_response.get('results')), 1)
        self.assertEqual(staff_response.get('count'), 1)

        # Give access and should see more unread.
        mommy.make(
            'sherpa.CampaignAccess',
            campaign=self.george_campaign,
            user_profile=self.staff_user.profile,
        )
        staff_response2 = self.staff_client.get(self.cp_unread_url).json()

        # Because we have a prospect with unread messages on two campaigns, we get those results
        # but they are not double counted, the count is for the amount of prospects with unread sms
        self.assertEqual(len(staff_response2.get('results')), 4)
        self.assertEqual(staff_response2.get('count'), 3)

        # Verify that admin users can see all unread messages.
        admin_response = self.george_client.get(self.cp_unread_url).json()
        self.assertEqual(len(admin_response.get('results')), 4)
        self.assertEqual(admin_response.get('count'), 3)
        for cp_data in admin_response.get('results'):
            self.assertEqual(type(cp_data.get('campaign')), dict)
            self.assertEqual(type(cp_data.get('prospect')), dict)

        # Verify can get count only
        count_only_response = self.george_client.get(f'{self.cp_unread_url}?include_messages=false')
        self.assertEqual(len(count_only_response.json().get('results')), 0)

    def test_is_campaign_prospects_unread_count_and_results_consistent(self):
        """
        In cases where prospects are in many campaigns, and have unread messages on more than
        one campaign, and we have many prospects with unread messages, the count of prospects
        and the amount of prospects in the results could differ if not properly handled.
        If for example, we have 100 prospects with unread messages in 3 different campaigns each
        that amounts to 300 campaignprospect results. A naive way of paginating would cut off
        at 100 campaignprospects.
        However that could get us as little as 34 prospects represented on the results set.
        """
        campaign_company_id = self.george_campaign2.company_id
        campaign_owner_id = self.george_campaign2.owner_id

        # We create the campaigns, prospects, and campaignprospects for the scenario
        campaigns = [mommy.make(
            'sherpa.Campaign',
            name=f"George Campaign {i}",
            company_id=campaign_company_id,
            owner_id=campaign_owner_id,
        ) for i in range(3)]

        prospects = [mommy.make(
            'sherpa.Prospect',
            company_id=campaign_company_id,
            phone_raw=str(4255557000 + i),
            phone_type='mobile',
        ) for i in range(100)]

        campaignprospects = []

        # Create campaignprospects entries and update them to have unread sms
        for prospect in prospects:
            for campaign in campaigns:
                campaignprospects.append(mommy.make(
                    'sherpa.CampaignProspect',
                    prospect=prospect,
                    campaign=campaign,
                ))

                campaign.has_unread_sms = True
                campaign.save()

            prospect.has_unread_sms = True
            prospect.save()

        admin_response = self.george_client.get(self.cp_unread_url).json()
        results = admin_response.get('results')

        self.assertEqual(admin_response.get('count'), 100)
        received_prospects = set([result["prospect"]["id"] for result in results])
        self.assertEqual(len(received_prospects), 100)
        # The viewset limits results to 200 for performance
        self.assertEqual(len(results), 200)

    def test_bulk_action_dnc(self):
        self.george_campaign_prospect.prospect.toggle_do_not_call(self.george_user, True)
        self.george_campaign_prospect.refresh_from_db()
        self.assertTrue(self.george_campaign_prospect.prospect.do_not_call)

        url = reverse('campaignprospect-bulk-action')
        response = self.george_client.post(
            url,
            {
                'values': [self.george_campaign_prospect.pk],
                'action': 'dnc',
            },
        )
        self.george_campaign_prospect.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.george_campaign_prospect.prospect.do_not_call)

    def test_bulk_action_priority(self):
        self.george_campaign_prospect.prospect.toggle_is_priority(self.george_user, False)
        self.george_campaign_prospect.refresh_from_db()
        self.assertFalse(self.george_campaign_prospect.prospect.is_priority)

        url = reverse('campaignprospect-bulk-action')
        response = self.george_client.post(
            url,
            {
                'values': [self.george_campaign_prospect.pk],
                'action': 'priority',
            },
        )
        self.george_campaign_prospect.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.george_campaign_prospect.prospect.is_priority)

    def test_bulk_action_verified(self):
        self.george_campaign_prospect.prospect.toggle_owner_verified(self.george_user, 'open')
        self.george_campaign_prospect.refresh_from_db()
        self.assertEqual(self.george_campaign_prospect.prospect.owner_verified_status, 'open')

        url = reverse('campaignprospect-bulk-action')
        response = self.george_client.post(
            url,
            {
                'values': [self.george_campaign_prospect.pk],
                'action': 'verify',
            },
        )
        self.george_campaign_prospect.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.george_campaign_prospect.prospect.owner_verified_status, 'verified')

    def test_bulk_action_mark_as_viewed(self):
        self.assertFalse(self.george_campaign_prospect.has_been_viewed)

        url = reverse('campaignprospect-bulk-action')
        response = self.george_client.post(
            url,
            {
                'values': [self.george_campaign_prospect.pk],
                'action': 'viewed',
            },
        )
        self.george_campaign_prospect.refresh_from_db()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.george_campaign_prospect.has_been_viewed)

    def test_auto_dead_unviewed_filter(self):
        self.george_prospect2.toggle_autodead(True)
        self.george_prospect2.refresh_from_db()
        self.assertEquals(self.george_prospect2.lead_stage.lead_stage_title, 'Dead (Auto)')

        # Test unviewed auto dead
        self.assertFalse(self.george_campaign_prospect2.has_been_viewed)
        params = {'campaign': self.george_campaign.pk, 'dead_auto_unviewed': True}
        response = self.george_client.get(self.list_url, params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

        self.george_campaign_prospect2.has_been_viewed = True
        self.george_campaign_prospect2.save(update_fields=['has_been_viewed'])
        self.george_campaign_prospect2.refresh_from_db()

        self.assertTrue(self.george_campaign_prospect2.has_been_viewed)
        params = {'campaign': self.george_campaign.pk, 'dead_auto_unviewed': True}
        response = self.george_client.get(self.list_url, params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 0)

        # Test all auto dead
        lead_stage = LeadStage.objects.get(company=self.company1, lead_stage_title='Dead (Auto)')
        params = {'campaign': self.george_campaign.pk, 'lead_stage': lead_stage.pk}
        response = self.george_client.get(self.list_url, params)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['count'], 1)

    def test_can_update_campaign_prospect(self):
        payload = {'hasBeenViewed': True}
        response = self.george_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 200)
        self.george_campaign_prospect.refresh_from_db()
        self.assertTrue(self.george_campaign_prospect.has_been_viewed)

    def test_cant_update_other_cp(self):
        payload = {'hasBeenViewed': True}
        response = self.thomas_client.patch(self.detail_url, payload)
        self.assertEqual(response.status_code, 404)
