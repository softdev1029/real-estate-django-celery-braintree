from model_mommy import mommy

from campaigns.tests import CampaignDataMixin
from sherpa.models import (
    CampaignProspect,
    LeadStage,
    PhoneNumber,
    PhoneType,
)
from sherpa.tests import BaseAPITestCase


class CampaignProspectModelTestCase(CampaignDataMixin, BaseAPITestCase):
    test_sherpa_number = '5097775555'

    def test_campaign_prospect_lead_stage_set(self):
        cp = self.george_campaign_prospect
        self.assertEqual(cp.prospect.lead_stage, None)
        cp.prospect.set_lead_stage()
        cp.refresh_from_db()
        expected = LeadStage.objects.filter(
            is_active=True,
            company=cp.prospect.company,
        ).order_by('sort_order').first()
        prospect = cp.prospect
        prospect.refresh_from_db()
        self.assertEqual(prospect.lead_stage, expected)
        self.assertEqual(prospect.lead_stage.lead_stage_title, expected.lead_stage_title)
        self.assertEqual(prospect.lead_stage.sort_order, expected.sort_order)

    def test_set_lead_stage_with_title(self):
        self.george_campaign_prospect.prospect.set_lead_stage()
        self.george_campaign_prospect.prospect.lead_stage.lead_stage_title = 'Oops!'
        self.george_campaign_prospect.prospect.lead_stage.save()
        self.george_campaign_prospect.prospect.set_lead_stage()

    def test_assign_phone_number(self):
        for _ in range(20):
            mommy.make('PhoneNumber', company=self.company1, market=self.market1, provider='telnyx')

        phone_number_list = []
        prospect_qs = self.company1.prospect_set.filter(sherpa_phone_number_obj=None)
        for prospect in prospect_qs:
            cp = prospect.campaignprospect_set.first()
            phone_number = cp.assign_number()
            self.assertNotIn(phone_number, phone_number_list)
            phone_number_list.append(phone_number)
            self.assertNotEqual(prospect.sherpa_phone_number_obj.phone, "")

    def test_retain_assigned_phone_number(self):
        for _ in range(20):
            mommy.make(
                'PhoneNumber',
                company=self.company1,
                market=self.market1,
                provider='telnyx',
                status=PhoneNumber.Status.ACTIVE,
            )

        # Assign some numbers and save which prospect is with which number.
        cp_queryset = CampaignProspect.objects.filter(prospect__company=self.company1)
        for cp in cp_queryset:
            cp.assign_number()
            cp.campaign.is_followup = True
            cp.campaign.retain_numbers = True
            cp.campaign.save()
            self.assertNotEqual(cp.prospect.sherpa_phone_number_obj, None)

        original_phone_numbers = {}
        for prospect in self.company1.prospect_set.all():
            original_phone_numbers[prospect.id] = prospect.sherpa_phone_number_obj

        # Reset the last one to not have a sherpa phone number obj, to test that situation as well.
        cp.sherpa_phone_number_obj = None
        cp.save()

        for cp in cp_queryset:
            updated = cp.assign_number()
            self.assertEqual(original_phone_numbers.get(cp.prospect.id), updated)

    def test_number_stays_assigned(self):
        phone_number = self.george_campaign_prospect.assign_number()
        followup_campaign = self.george_campaign.create_followup(
            self.george_user,
            'followup name',
            retain_numbers=True,
        )
        self.george_campaign_prospect.campaign = followup_campaign
        self.george_campaign_prospect.save()

        new_number = self.george_campaign_prospect.assign_number()
        self.assertEqual(phone_number, new_number)

    def test_clone_prospect(self):
        original = self.george_campaign_prospect
        self.assertNotEqual(original.prospect.sherpa_phone_number_obj, None)
        original_count = PhoneType.objects.count()
        data = {}

        # Check that phone raw is required.
        try:
            original.clone(data)
            self.fail('`phone_raw` should be required for cloning.')
        except KeyError:
            pass

        # Verify the campaign prospect is cloned.
        data['phone_raw'] = '5095391234'
        data['property_address'] = '827 fake st'
        data['first_name'] = 'Billy'
        cloned_campaign_prospect = original.clone(data)

        # Also verify the prospect data.
        cloned_prospect = cloned_campaign_prospect.prospect
        self.assertEqual(cloned_prospect.phone_raw, '5095391234')
        self.assertEqual(cloned_prospect.property_address, '827 fake st')
        self.assertEqual(cloned_prospect.first_name, 'Billy')
        self.assertEqual(
            cloned_prospect.sherpa_phone_number_obj, original.prospect.sherpa_phone_number_obj)

        # Last but not least, the new phone type record.
        self.assertEqual(PhoneType.objects.count(), original_count + 1)

    def test_count_prospect(self):
        cp = self.george_campaign_prospect
        mommy.make('sherpa.PhoneType', phone=cp.prospect.phone_raw)

        # Does not count if prospect is verizon
        phone_type = cp.prospect.phone_data
        phone_type.carrier = 'Verizon'
        phone_type.save()
        cp.count_prospect(True, True, True)
        cp.refresh_from_db()
        self.assertTrue(cp.count_as_unique)
        self.assertFalse(cp.include_in_upload_count)

        # Landlines should not count against monthly update count.
        phone_type.type = PhoneType.Type.LANDLINE
        phone_type.carrier = 'Sprint'
        phone_type.save()
        cp.count_prospect(True, True, True)
        cp.refresh_from_db()
        self.assertTrue(cp.count_as_unique)
        self.assertFalse(cp.include_in_upload_count)

        # And finally check that with the proper criteria, prospect counts against monthly.
        phone_type.type = PhoneType.Type.MOBILE
        phone_type.save()
        cp.count_prospect(True, True, True)
        cp.refresh_from_db()
        self.assertTrue(cp.count_as_unique)
        self.assertTrue(cp.include_in_upload_count)

        # Does count if prospect is verizon and uses twilio
        mommy.make(
            'companies.TelephonyConnection',
            company=cp.prospect.company,
            api_key='apikey',
            api_secret='apisecret',
        )
        phone_type.carrier = 'Verizon'
        phone_type.save()
        cp.count_prospect(True, True, True)
        cp.refresh_from_db()
        self.assertTrue(cp.count_as_unique)
        self.assertTrue(cp.include_in_upload_count)
