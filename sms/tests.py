from time import sleep

from model_mommy import mommy

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse

from campaigns.models import InitialResponse
from campaigns.tests import CampaignDataMixin
from prospects.models import ProspectRelay, RelayNumber
from sherpa.models import PhoneNumber, SMSMessage, SMSPrefillText, SMSTemplate
from sherpa.tests import (
    AdminUserMixin,
    BaseAPITestCase,
    BaseTestCase,
    CompanyOneMixin,
    CompanyTwoMixin,
    NoDataBaseTestCase,
)
from . import OPT_OUT_LANGUAGE
from .clients import TelnyxClient
from .models import CarrierApprovedTemplate, SMSResult, SMSTemplateCategory
from .tasks import (
    record_phone_number_stats_received,
    sms_message_received,
    track_sms_reponse_time_task,
    update_template_stats,
)
from .utils import find_banned_words, find_spam_words, get_tags


class SMSTemplateModelTestCase(CompanyOneMixin, NoDataBaseTestCase):

    def setUp(self):
        self.invalid_template = mommy.make(
            'sherpa.SMSTemplate',
            message='invalid message',
            alternate_message='invalid alternate {CompanyName}',
            company=self.company1,
        )

    def test_valid_message_templates(self):
        self.assertFalse(self.invalid_template.has_required_outgoing_tags)

        # Now we can make it valid.
        self.invalid_template.message = 'invalid {CompanyName}'
        self.invalid_template.save()
        self.assertTrue(self.invalid_template.has_required_outgoing_tags)

        # Now let's test the invalid message.
        self.invalid_template.alternate_message = 'invalid'
        self.invalid_template.save()
        self.assertFalse(self.invalid_template.has_required_outgoing_tags)

    def test_get_alternate_message(self):
        template = self.invalid_template
        template.get_alternate_message(opt_out_language=OPT_OUT_LANGUAGE)

        # Now make it valid and get the alternate message.
        template.alternate_message = 'invalid alternate {CompanyName}'
        template.save()
        alternate_message = template.get_alternate_message(opt_out_language=OPT_OUT_LANGUAGE)
        self.assertIn(self.company1.random_outgoing_company_name, alternate_message)
        self.assertIn(OPT_OUT_LANGUAGE, alternate_message)


class SMSTemplateAPITestCase(CompanyTwoMixin, AdminUserMixin, CompanyOneMixin, NoDataBaseTestCase):
    sms_template_list_url = reverse('smstemplate-list')
    valid_template_list_url = reverse('smstemplate-list-valid')

    def setUp(self):
        super(SMSTemplateAPITestCase, self).setUp()
        valid_message = "From {CompanyName}"
        cat = mommy.make(
            'sms.SMSTemplateCategory',
            company=self.company1,
            title='Category-Test',
        )
        self.template1 = mommy.make(
            'sherpa.SMSTemplate',
            id=1,
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            sort_order=1,
            category=cat,
        )
        self.template2 = mommy.make(
            'sherpa.SMSTemplate',
            id=2,
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            sort_order=2,
            category=cat,
        )

        self.template3 = mommy.make(
            'sherpa.SMSTemplate',
            id=3,
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            sort_order=3,
            category=cat,
        )
        self.template4 = mommy.make(
            'sherpa.SMSTemplate',
            id=4,
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            sort_order=4,
            category=cat,
        )

        self.template5 = mommy.make(
            'sherpa.SMSTemplate',
            id=5,
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            sort_order=5,
            category=cat,
        )

        self.company2_template = mommy.make('sherpa.SMSTemplate', company=self.company2)
        self.sms_template_detail_url = reverse('smstemplate-detail', kwargs={
            'pk': self.template1.pk,
        })

    def test_unauth_cant_get_templates(self):
        response = self.client.get(self.sms_template_list_url)
        self.assertEqual(response.status_code, 401)

    def test_user_can_get_their_templates(self):
        response = self.admin_client.get(self.sms_template_list_url)
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results), self.company1.smstemplate_set.count())

        for template_data in results:
            self.assertEqual(template_data.get('company'), self.company1.id)

    def test_user_can_set_their_alternate_message(self):
        payload = {'alternate_message': 'test message {CompanyName}'}
        response = self.admin_client.patch(self.sms_template_detail_url, payload)
        self.assertEqual(response.status_code, 200)

    def test_user_cant_set_others_alternate_message(self):
        payload = {'alternate_message': 'test message'}
        response = self.company2_client.patch(self.sms_template_detail_url, payload)
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json().get('detail'), 'Not found.')

    def test_user_can_copy_their_alternate_message(self):
        payload = {'message': 'test message'}
        response = self.admin_client.post(
            self.sms_template_detail_url + 'copy_alternate_message/', payload)
        self.assertEqual(response.status_code, 200)
        self.template1.company.refresh_from_db()
        self.assertEqual(self.template1.company.default_alternate_message, 'test message')

    def test_user_cannot_use_brackets_in_alternate_message(self):
        payload = {'alternate_message': 'test {message}'}
        response = self.admin_client.patch(self.sms_template_detail_url, payload)
        self.assertEqual(response.status_code, 400)

    def test_user_can_create_sms_template(self):
        payload = {
            'template_name': 'test name of template',
            'message': 'hello {FirstName}, I am {CompanyName} in a test suite.',
            'alternate_message': 'this is alternate... {CompanyName}',
            'category': self.company1.template_categories.first().id,
        }
        response = self.master_admin_client.post(self.sms_template_list_url, payload)
        self.assertEqual(response.status_code, 201)

        # Verify some basic data in the response and created record.
        self.assertEqual(response.json().get('templateName'), 'test name of template')
        sms_template = SMSTemplate.objects.get(id=response.json().get('id'))
        self.assertEqual(sms_template.created_by, self.master_admin_user)
        self.assertEqual(sms_template.company, self.company1)

    def test_doesnt_get_templates_with_banned_words(self):
        with_banned = f'hello {settings.BANNED_WORDS[0]}, I am in a test suite.'
        self.template1.message = with_banned
        self.template1.save()
        response = self.admin_client.get(self.valid_template_list_url)
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results) + 1, self.company1.smstemplate_set.count())

    def test_banned_word_only_full_word(self):
        # Endpoint is deprecated.
        with_banned = f'hello {settings.BANNED_WORDS[0]}s, I am in a test suite.'
        self.template1.message = with_banned
        self.template1.save()

        response = self.admin_client.get(self.valid_template_list_url)
        self.assertEqual(response.status_code, 200)

    def test_banned_word_case_insensitive(self):
        with_banned = f'hello {settings.BANNED_WORDS[0]}, I am in a test suite.'
        self.template1.message = with_banned
        self.template1.save()

        response = self.admin_client.get(self.valid_template_list_url)
        self.assertEqual(response.status_code, 200)
        results = response.json()
        self.assertEqual(len(results) + 1, self.company1.smstemplate_set.count())

    def test_cant_save_with_link(self):
        links = [
            'https://www.example.com',
            'http://www.example.com',
            'www.example.com',
        ]

        for link in links:
            payload = {
                'template_name': 'test name of template',
                'message': f'hello go here {link}',
                'alternate_message': 'this is alternate...',
            }
            response = self.admin_client.post(self.sms_template_list_url, payload)
            self.assertEqual(response.status_code, 400)

    def test_cant_create_invalid_template_tags(self):
        invalid = ['With an {incomplete tag', 'With a {NonExistant} tag']
        url = self.sms_template_list_url
        for message in invalid:
            payload = {
                'template_name': 'test name of template',
                'message': message,
                'alternate_message': 'this is alternate...',
            }
            response = self.admin_client.post(url, payload)
            self.assertEqual(response.status_code, 400)
            self.assertNotEqual(response.json().get('message'), None)

    def test_cant_save_banned_word(self):
        # Check that we can't create new.
        banned_words = settings.BANNED_WORDS
        payload = {
            'template_name': 'test name of template',
            'message': f"Hi {banned_words[0]}, could I politely offer you a {banned_words[1]}?",
            'alternate_message': 'this is alternate...',
        }
        response = self.master_admin_client.post(self.sms_template_list_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Message may not contain banned words', response.json().get('message')[0])

        # Check that we can't update existing.
        payload = {
            'message': f'hello there, {banned_words[0]}',
        }
        response2 = self.admin_client.post(self.sms_template_list_url, payload)
        self.assertEqual(response2.status_code, 400)
        self.assertIn('Message may not contain banned words', response2.json().get('message')[0])

    def test_cant_save_spam_word(self):
        # Check that we can't create new.
        spam_words = settings.SPAM_WORDS
        payload = {
            'template_name': 'test name of template',
            'message': f"Hi {spam_words[0]}, could I politely offer you a {spam_words[1]}?",
            'alternate_message': 'this is alternate...',
        }
        response = self.master_admin_client.post(self.sms_template_list_url, payload)
        self.assertEqual(response.status_code, 400)
        self.assertIn('Message may not contain spam words', response.json().get('message')[0])

        # Check that we can't update existing.
        payload = {
            'message': f'hello there, {spam_words[0]}',
        }
        response2 = self.admin_client.post(self.sms_template_list_url, payload)
        self.assertEqual(response2.status_code, 400)
        self.assertIn('Message may not contain spam words', response2.json().get('message')[0])


class ProspectRelayModelTestCase(CampaignDataMixin, BaseTestCase):
    def test_get_error_if_no_relay_numbers(self):
        agent = self.thomas_user.profile
        prospect = self.thomas_prospect
        relay, error = ProspectRelay.connect(agent, prospect)
        self.assertIsNone(relay)
        self.assertEqual(error, 'no_available_relay_numbers')

    def test_can_connect_and_disconnect_relay(self):
        # Can create connection
        number = mommy.make('RelayNumber', status=RelayNumber.Status.ACTIVE)
        agent = self.thomas_user.profile
        prospect = self.thomas_prospect
        relay, error = ProspectRelay.connect(agent, prospect)
        self.assertIsNone(error)
        self.assertEqual(relay.relay_number.pk, number.pk)
        self.assertEqual(relay.agent_profile.pk, agent.pk)
        self.assertEqual(relay.prospect.pk, prospect.pk)
        self.assertEqual(prospect.relay.pk, relay.pk)

        # Can disconnect relay
        relay.disconnect()
        self.assertIsNone(prospect.relay)

    def test_get_error_if_maximum_connections(self):
        # make max connections
        for i in range(settings.TELNYX_RELAY_CONNECTIONS):
            mommy.make('RelayNumber', status=RelayNumber.Status.ACTIVE)
            agent = self.thomas_user.profile
            prospect = mommy.make('Prospect', company=agent.company)
            mommy.make('CampaignProspect', prospect=prospect, campaign=self.thomas_campaign)
            relay, error = ProspectRelay.connect(agent, prospect)
            self.assertIsNone(error)

        # make one more connection, should have error
        agent = self.thomas_user.profile
        prospect = mommy.make('Prospect', company=agent.company)
        mommy.make('CampaignProspect', prospect=prospect, campaign=self.thomas_campaign)
        relay, error = ProspectRelay.connect(agent, prospect)
        self.assertIsNone(relay)
        self.assertEqual(error, 'max_assignment_limit_reached')


class SMSTaskTestCase(CampaignDataMixin, BaseTestCase):

    def receive_message(self, **kwargs):
        """
        Optionally pass in kwargs `from_number`, `to_number`, `message` to fake receiving a message.
        """
        if not kwargs.get('from_number'):
            kwargs['from_number'] = self.george_prospect.phone_raw

        if not kwargs.get('to_number'):
            kwargs['to_number'] = self.george_prospect.sherpa_phone_number_obj.phone

        if not kwargs.get('message'):
            kwargs['message'] = 'this is a test message from prospect 1'

        kwargs['num_media'] = None
        kwargs['file_extension'] = None
        kwargs['media_url'] = None
        sms_message_received(**kwargs)

    def test_receiving_message_creates_an_sms_message(self):
        initial_count = SMSMessage.objects.count()
        self.receive_message()
        self.assertEqual(SMSMessage.objects.count(), initial_count + 1)

    def test_reply_records_response_time(self):
        self.assertEqual(SMSMessage.objects.count(), 0)
        self.receive_message()
        message = SMSMessage.objects.last()

        # Verify starting data is correct.
        self.assertEqual(message.response_time_seconds, 0)
        self.assertEqual(message.response_dt, None)
        self.assertEqual(message.response_from_rep, None)

        # Reply to the message and check that the data has been updated.
        sleep(1)
        track_sms_reponse_time_task(self.george_prospect.id, self.george_user.id)
        message.refresh_from_db()
        self.assertEqual(message.response_from_rep, self.george_user)
        self.assertNotEqual(message.response_dt, None)
        self.assertTrue(message.response_time_seconds > 0)

    def test_create_initial_message_received(self):
        self.assertEqual(InitialResponse.objects.count(), 0)
        self.receive_message()
        self.assertEqual(InitialResponse.objects.count(), 1)

        # Check that it does not create multiple initial messages.
        self.receive_message()
        self.assertEqual(InitialResponse.objects.count(), 1)

    def test_create_initial_message_not_autodead(self):
        # disable the autodead in campaign
        self.george_campaign.set_auto_dead = False
        self.george_campaign.save()
        self.receive_message(message='no')
        initial_message = InitialResponse.objects.first()
        self.assertFalse(initial_message.is_auto_dead)

    def test_create_initial_message_is_autodead(self):
        self.receive_message(message='no')
        initial_message = InitialResponse.objects.first()
        self.assertTrue(initial_message.is_auto_dead)

    def test_cant_create_duplicate_initial_response(self):
        self.receive_message()
        initial_count = InitialResponse.objects.count()
        try:
            InitialResponse.objects.create(
                message=self.george_prospect.messages.first(),
                campaign=self.george_campaign,
            )
            self.fail('should not be able to create duplicate')
        except Exception:
            self.assertEqual(InitialResponse.objects.count(), initial_count)

    def test_prospect_blocked(self):
        initial_count = SMSMessage.objects.count()
        self.george_prospect.is_blocked = True
        self.george_prospect.save()
        self.receive_message(message='blocked')
        final_count = SMSMessage.objects.count()
        self.assertEqual(initial_count, final_count)

    def test_record_received_date(self):
        phone = self.george_prospect.sherpa_phone_number_obj
        self.assertEqual(phone.last_received_utc, None)

        # Does not change if invalid or released.
        phone.status = PhoneNumber.Status.RELEASED
        phone.save()
        record_phone_number_stats_received('doesnotexist')
        record_phone_number_stats_received(phone.phone)
        phone.refresh_from_db()
        self.assertEqual(phone.last_received_utc, None)

        # Changes if inactive
        phone.status = PhoneNumber.Status.INACTIVE
        phone.save()
        record_phone_number_stats_received(phone.phone)
        phone.refresh_from_db()
        self.assertNotEqual(phone.last_received_utc, None)
        updated_last_received_utc = phone.last_received_utc

        # Changes if active
        phone.status = PhoneNumber.Status.ACTIVE
        phone.save()
        record_phone_number_stats_received(phone.phone)
        phone.refresh_from_db()
        self.assertTrue(phone.last_received_utc > updated_last_received_utc)

    def test_update_template_stats(self):
        template2 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            alternate_message=self.valid_message,
            message=self.valid_message,
        )
        template3 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            alternate_message=self.valid_message,
            message=self.valid_message,
        )

        # Let's make some messages that we're sending out, and fake the delivery status.
        m1 = mommy.make(
            'sherpa.SMSMessage', template=self.sms_template, prospect=self.george_prospect)
        m2 = mommy.make('sherpa.SMSMessage', template=self.sms_template)
        m3 = mommy.make('sherpa.SMSMessage', template=template2)
        mommy.make('sms.SMSResult', sms=m1, status=SMSResult.Status.DELIVERED)
        mommy.make('sms.SMSResult', sms=m2, status=SMSResult.Status.DELIVERY_FAILED)
        mommy.make('sms.SMSResult', sms=m3, status=SMSResult.Status.DELIVERY_FAILED)

        # Ok now let's fake some received messages.
        received = mommy.make('sherpa.SMSMessage', prospect=m1.prospect, from_prospect=True)
        mommy.make('campaigns.InitialResponse', message=received, campaign=self.george_campaign)

        # Now we can update the percentages and verify they were updated correctly.
        update_template_stats()
        self.sms_template.refresh_from_db()
        template2.refresh_from_db()
        template3.refresh_from_db()

        self.assertEqual(self.sms_template.delivery_percent, 50)
        # self.assertEqual(self.sms_template.response_rate, 50)
        self.assertEqual(template2.delivery_percent, 0)
        # self.assertEqual(template2.response_rate, 0)
        self.assertEqual(template3.delivery_percent, None)
        # self.assertEqual(template3.response_rate, None)

    def test_mark_as_wrong_number(self):
        # Test that wrong number isn't marked when it shouldn't be.
        self.company1.auto_dead_enabled = True
        self.company1.save(update_fields=['auto_dead_enabled'])
        self.receive_message(message='test message... nothing wrong here')
        self.george_prospect.refresh_from_db()
        self.assertFalse(self.george_prospect.wrong_number)

        # Check that wrong number is marked if 'wrong number' is in the message.
        # Verify that dnc is not marked.
        self.receive_message(message='You got the wRong numBer. Not me.')
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_prospect.wrong_number)
        self.assertFalse(self.george_prospect.do_not_call)


class SMSMessageAPITestCase(CampaignDataMixin, BaseAPITestCase):

    def setUp(self):
        super(SMSMessageAPITestCase, self).setUp()
        self.unread_message = mommy.make(
            'sherpa.SMSMessage',
            prospect=self.george_prospect,
            company=self.company1,
            from_prospect=False,
            message='this is from the prospect.',
            unread_by_recipient=True,
        )
        self.sms_message_detail_url = reverse('smsmessage-detail', kwargs={
            'pk': self.unread_message.id,
        })

    def test_can_mark_message_as_read(self):
        # First create another unread to make sure prospect not marked as read when they still have
        unread_message2 = mommy.make(
            'sherpa.SMSMessage',
            prospect=self.george_prospect,
            company=self.company1,
            from_prospect=False,
            message='this is another from the prospect.',
            unread_by_recipient=True,
        )
        self.george_prospect.has_unread_sms = True
        self.george_prospect.save()

        # Update one message to be read.
        first_url = reverse('smsmessage-detail', kwargs={'pk': unread_message2.id})
        payload = {'unreadByRecipient': False}
        response = self.george_client.patch(first_url, payload)
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json().get('unreadByRecipient'))
        unread_message2.refresh_from_db()
        self.george_prospect.refresh_from_db()
        self.assertFalse(unread_message2.unread_by_recipient)
        self.assertTrue(self.george_prospect.has_unread_sms)

        # Now mark the other message as read.
        self.george_client.patch(self.sms_message_detail_url, payload)
        self.unread_message.refresh_from_db()
        self.george_prospect.refresh_from_db()
        self.assertFalse(self.unread_message.unread_by_recipient)
        self.assertFalse(self.george_prospect.has_unread_sms)

    def test_cant_mark_others_message_as_read(self):
        payload = {'unreadByRecipient': False}
        response = self.thomas_client.patch(self.sms_message_detail_url, payload)
        self.assertEqual(response.status_code, 404)


class SMSMessageModelTestCase(CampaignDataMixin, BaseAPITestCase):

    def __set_as_unread(self):
        """
        Set george prospect and their related data to be unread.
        """
        self.george_prospect.has_unread_sms = True
        self.george_prospect.save()

        for campaign in self.george_prospect.campaign_qs:
            campaign.has_unread_sms = True
            campaign.save()

        for campaign_prospect in self.george_prospect.campaignprospect_set.all():
            # Note: this is deprecated and we'll be removing unread from `CampaignProspect`
            campaign_prospect.has_unread_sms = True
            campaign_prospect.save()

    def test_set_unread_indicators(self):
        self.__set_as_unread()

        # Check that batch message does not set as read
        message = SMSMessage.objects.create(
            prospect=self.george_prospect, campaign=self.george_campaign)
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_prospect.has_unread_sms)

        # Check that updating just status does not set indicators
        message.message_status = 'delivered'
        message.save(update_fields=['message_status'])
        self.george_prospect.refresh_from_db()
        self.assertTrue(self.george_prospect.has_unread_sms)

        # Create new message outside of campaign for prospect1 and should all be read.
        SMSMessage.objects.create(prospect=self.george_prospect)
        self.george_prospect.refresh_from_db()
        self.assertFalse(self.george_prospect.has_unread_sms)

        for campaign in self.george_prospect.campaign_qs:
            self.assertFalse(campaign.has_unread_sms)

        for campaign_prospect in self.george_prospect.campaignprospect_set.all():
            self.assertFalse(campaign_prospect.has_unread_sms)


class QuickReplyAPITestCase(CampaignDataMixin, BaseAPITestCase):
    quick_reply_list_url = reverse('quickreply-list')

    def setUp(self):
        super(QuickReplyAPITestCase, self).setUp()
        self.george_quick_reply = mommy.make(
            'sherpa.SMSPrefillText', sort_order=0, company=self.company1)
        mommy.make('sherpa.SMSPrefillText', sort_order=4, company=self.company1)  # max sort
        mommy.make('sherpa.SMSPrefillText', sort_order=3, company=self.company1)
        mommy.make('sherpa.SMSPrefillText', sort_order=1, company=self.company1)
        mommy.make('sherpa.SMSPrefillText', sort_order=2, company=self.company1)

        mommy.make('sherpa.SMSPrefillText', sort_order=1, company=self.company2)
        self.quick_reply1 = mommy.make('sherpa.SMSPrefillText', sort_order=2, company=self.company2)
        mommy.make('sherpa.SMSPrefillText', sort_order=3, company=self.company2)
        self.quick_reply2 = mommy.make('sherpa.SMSPrefillText', sort_order=4, company=self.company2)
        mommy.make('sherpa.SMSPrefillText', sort_order=5, company=self.company2)
        self.current_max_sort_order = 1 + 4

        self.detail_url = reverse('quickreply-detail', kwargs={'pk': self.george_quick_reply.pk})

    def test_can_fetch_quick_replies(self):
        response = self.george_client.get(self.quick_reply_list_url)
        data = response.json()

        # Verify that the data is filtered to company.
        expected_count = self.company1.quick_replies.count()
        self.assertEqual(len(data), expected_count)

        # Verify ordering is correct.
        current_order = 0
        for prefill in data:
            instance = SMSPrefillText.objects.get(id=prefill.get('id'))
            self.assertTrue(instance.sort_order >= current_order)

    def test_quick_reply_create_and_update(self):
        payload = {
            'question': 'Where is this?',
            'message': 'This. IS. SPARTA!',
        }
        response = self.george_client.post(self.quick_reply_list_url, payload)
        data = response.json()
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.current_max_sort_order, data['sortOrder'])
        pk = data['id']
        response = self.george_client.put(
            reverse('quickreply-detail', kwargs={'pk': pk}),
            {
                'sort_order': 99,
                'question': 'What am I?',
                'message': "You're a wizard, Harry.",
            },
        )
        self.assertEqual(99, response.json()['sortOrder'])

    def test_quick_reply_rotate_sort(self):
        # Test sort order record moving up skipping over records.
        url = reverse('quickreply-detail', kwargs={'pk': self.quick_reply2.pk})
        response = self.thomas_client.patch(url, {'sortOrder': 2})
        self.assertEqual(response.status_code, 200)

        quick_replies = self.thomas_user.profile.company.quick_replies.all().order_by('id')
        sort_order = [1, 3, 4, 2, 5]
        for i, reply in enumerate(quick_replies):
            self.assertEqual(reply.sort_order, sort_order[i])

        self.reorder_quick_replies()

        # Test sort order record moving up by one.
        response = self.thomas_client.patch(url, {'sortOrder': 3})
        self.assertEqual(response.status_code, 200)

        quick_replies = self.thomas_user.profile.company.quick_replies.all().order_by('id')
        sort_order = [1, 2, 4, 3, 5]
        for i, reply in enumerate(quick_replies):
            self.assertEqual(reply.sort_order, sort_order[i])

        self.reorder_quick_replies()

        # Test sort order record moving down skipping over records.
        url = reverse('quickreply-detail', kwargs={'pk': self.quick_reply1.pk})
        response = self.thomas_client.patch(url, {'sortOrder': 4})
        self.assertEqual(response.status_code, 200)

        quick_replies = self.thomas_user.profile.company.quick_replies.all().order_by('id')
        sort_order = [1, 4, 2, 3, 5]
        for i, reply in enumerate(quick_replies):
            self.assertEqual(reply.sort_order, sort_order[i])

        self.reorder_quick_replies()

        # Test sort order record moving down by one.
        response = self.thomas_client.patch(url, {'sortOrder': 3})
        self.assertEqual(response.status_code, 200)

        quick_replies = self.thomas_user.profile.company.quick_replies.all().order_by('id')
        sort_order = [1, 3, 2, 4, 5]
        for i, reply in enumerate(quick_replies):
            self.assertEqual(reply.sort_order, sort_order[i])

    def test_remove_sort_rotate(self):
        self.reorder_quick_replies()

        # Test removing record completely.
        url = reverse('quickreply-detail', kwargs={'pk': self.quick_reply1.pk})
        response = self.thomas_client.delete(url)
        self.assertEqual(response.status_code, 204)

        quick_replies = self.thomas_user.profile.company.quick_replies.all().order_by('id')
        sort_order = [1, 2, 3, 4]
        for i, reply in enumerate(quick_replies):
            self.assertEqual(reply.sort_order, sort_order[i])

    def reorder_quick_replies(self):
        """
        Helper method to that reorders Thomas' quick replies sorts ordered by ID.
        """
        quick_replies = self.thomas_user.profile.company.quick_replies.all().order_by('id')
        for i, reply in enumerate(quick_replies):
            reply.sort_order = i + 1
            reply.save()

    def test_cant_create_invalid_qr_message_tags(self):
        invalid = ['With an {incomplete tag', 'With a {NonExistant} tag']
        url = self.quick_reply_list_url
        for message in invalid:
            payload = {
                'question': 'test name of template',
                'message': message,
            }
            response = self.george_client.post(url, payload)
            self.assertEqual(response.status_code, 400)
            self.assertNotEqual(response.json().get('message'), None)

    def test_cant_save_banned_word(self):
        # Check that we can't create new.
        banned_words = settings.BANNED_WORDS
        payload = {
            'question': 'Where is this?',
            'message': f'This. IS. {banned_words[0]}!',
        }
        response = self.george_client.post(self.quick_reply_list_url, payload)
        self.assertTrue(
            'Message may not contain banned words' in response.json().get('message')[0])

        # Check that we can't update existing.
        payload = {
            'message': f'hello there, {banned_words[0]}',
        }
        response2 = self.george_client.patch(self.detail_url, payload)
        self.assertEqual(response2.status_code, 400)
        self.assertTrue(
            'Message may not contain banned words' in response2.json().get('message')[0])

    def test_can_send_spam_word(self):
        # Check that we can't create new.
        spam_words = settings.SPAM_WORDS
        payload = {
            'question': 'Where is this?',
            'message': f'This. IS. {spam_words[0]}!',
        }
        response = self.george_client.post(self.quick_reply_list_url, payload)
        self.assertEqual(response.status_code, 201)

        # Check that we can't update existing.
        payload = {
            'message': f'hello there, {spam_words[0]}',
        }
        response2 = self.george_client.patch(self.detail_url, payload)
        self.assertEqual(response2.status_code, 200)


class SMSCommandTestCase(NoDataBaseTestCase):
    def test_add_carrier_approved_template_command(self):
        mommy.make(
            'sms.CarrierApprovedTemplate',
            message='first message',
            alternate_message='alternate_message',
        )
        call_command('add_carrier_approved_template', 'second message')
        template = CarrierApprovedTemplate.objects.order_by('id').last()
        self.assertEqual(template.message, 'second message')
        self.assertEqual(template.alternate_message, 'alternate_message')


class SMSUtilTestCase(NoDataBaseTestCase):
    def test_get_tags_of_message(self):
        message = 'This is a {MergeTag} and here is {Another}.'
        merge_tags = get_tags(message)
        self.assertEqual(merge_tags, ['MergeTag', 'Another'])

    def test_check_banned_words(self):
        clean = 'This is a clean string.  Assess the situation.'  # "Hidden" banned word.
        bad_word = settings.BANNED_WORDS[0]
        dirty = f'This is a dirty {bad_word} string.'
        bad_word2 = settings.BANNED_WORDS[7]
        dirty2 = f'This is a dirty {bad_word} string, {bad_word2}!'
        self.assertEqual(find_banned_words(clean), [])
        self.assertEqual(find_banned_words(dirty), [bad_word])
        self.assertEqual(find_banned_words(dirty2), [bad_word, bad_word2])

    def test_check_spam_words(self):
        clean = 'This is a clean string. afapologizesd.'  # "Hidden" spam word.
        bad_word = settings.SPAM_WORDS[0]
        dirty = f'This is a dirty {bad_word} string.'
        bad_word2 = settings.SPAM_WORDS[7]
        dirty2 = f'This is a dirty {bad_word} string, {bad_word2}!'
        self.assertEqual(find_spam_words(clean), [])
        self.assertEqual(find_spam_words(dirty), [bad_word])
        self.assertEqual(find_spam_words(dirty2), [bad_word, bad_word2])


class SMSClientTestCase(NoDataBaseTestCase):
    def setUp(self):
        self.telnyx_client = TelnyxClient()

    def test_cant_fetch_number_poorly_formatted_phone(self):
        cases = [
            '',
            '31288877777',
            '328887777',
            '3288a7777',
        ]
        for case in cases:
            with self.assertRaises(ValidationError):
                self.telnyx_client.fetch_number(case, raise_errors=True)

            # If we run this without raise_errors, it should run and return 'na'
            response = self.telnyx_client.fetch_number(case)
            self.assertTrue(response['name'] == 'na')

    def test_can_fetch_number_correctly_formatted_phone(self):
        # Allows phones with and without '1' added as some phones might be
        # saved with the leading '1' and others are not.
        cases = [
            '13128887777',
            '3128887777',
            '2222222222',  # should work but return blank data
        ]
        for case in cases:
            response = self.telnyx_client.fetch_number(case)
            self.assertTrue('name' in response.keys())
            self.assertTrue('type' in response.keys())
        self.assertIsNone(response['name'])


class SMSTemplateCategoryAPITestCase(CampaignDataMixin, BaseAPITestCase):
    category_list_url = reverse('smstemplatecategories-list')

    def setUp(self):
        super().setUp()
        valid_message = 'msg'
        self.category = mommy.make(
            'sms.SMSTemplateCategory',
            title='testcat',
            company=self.company1,
        )
        self.template5 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            category=self.category,
            sort_order=1,
        )
        self.template1 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            category=self.category,
            sort_order=2,
        )
        self.template3 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            category=self.category,
            sort_order=3,
        )
        self.template4 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            category=self.category,
            sort_order=4,
        )
        self.template2 = mommy.make(
            'sherpa.SMSTemplate',
            company=self.company1,
            message=valid_message,
            alternate_message=valid_message,
            category=self.category,
            sort_order=5,
        )

    def test_can_create_update_category(self):
        data = {'title': 'Category-5'}
        response = self.george_client.post(self.category_list_url, data)
        self.assertEqual(response.status_code, 201)
        category = SMSTemplateCategory.objects.get(id=response.json()['id'])
        self.assertEqual(data['title'], category.title)

        detail_url = reverse('smstemplatecategories-detail', kwargs={'pk': category.pk})
        data['title'] = 'Category-6'
        response = self.george_client.patch(detail_url, data)
        self.assertEqual(response.status_code, 200)
        category.refresh_from_db()
        self.assertEqual(data['title'], category.title)

    def test_can_sort_templates(self):
        url = reverse('smstemplatecategories-sort', kwargs={'pk': self.category.id})
        data = {
            'template': self.template2.id,
            'order': 1,
        }
        response = self.george_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.template2.refresh_from_db()
        self.assertEqual(self.template2.sort_order, 1)
        self.template5.refresh_from_db()
        self.assertEqual(self.template5.sort_order, 2)
        self.template1.refresh_from_db()
        self.assertEqual(self.template1.sort_order, 3)
        data = {
            'template': self.template1.id,
            'order': 5,
        }
        response = self.george_client.patch(url, data)
        self.template1.refresh_from_db()
        self.assertEqual(self.template1.sort_order, 5)
        self.template4.refresh_from_db()
        self.assertEqual(self.template4.sort_order, 4)

    def test_can_move_templates_to_new_category(self):
        # Fix the sorting to make testing easier.
        self.template1.sort_order = 1
        self.template1.save()
        self.template2.sort_order = 2
        self.template2.save()
        self.template3.sort_order = 3
        self.template3.save()
        self.template4.sort_order = 4
        self.template4.save()
        self.template5.sort_order = 5
        self.template5.save()
        self.template1.refresh_from_db()
        self.template2.refresh_from_db()
        self.template3.refresh_from_db()
        self.template4.refresh_from_db()
        self.template5.refresh_from_db()

        new_cat = mommy.make(
            'sms.SMSTemplateCategory',
            title='new testcat',
            company=self.company1,
        )
        data = {
            'category': new_cat.id,
        }
        url = reverse('smstemplate-detail', kwargs={
            'pk': self.template1.pk,
        })
        response = self.george_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.template1.refresh_from_db()
        self.template2.refresh_from_db()
        self.template3.refresh_from_db()
        self.assertEqual(self.template1.sort_order, 1)
        self.assertEqual(self.template2.sort_order, 1)
        self.assertEqual(self.template3.sort_order, 2)

        url = reverse('smstemplate-detail', kwargs={
            'pk': self.template4.pk,
        })
        response = self.george_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.template4.refresh_from_db()
        self.template5.refresh_from_db()
        self.assertEqual(self.template4.sort_order, 2)
        self.assertEqual(self.template5.sort_order, 3)

        data = {
            'category': new_cat.id,
            'sort_order': 1,
        }
        url = reverse('smstemplate-detail', kwargs={
            'pk': self.template2.pk,
        })
        response = self.george_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.template1.refresh_from_db()
        self.template2.refresh_from_db()
        self.template3.refresh_from_db()
        self.template4.refresh_from_db()
        self.template5.refresh_from_db()
        self.assertEqual(self.template2.sort_order, 1)
        self.assertEqual(self.template1.sort_order, 2)
        self.assertEqual(self.template4.sort_order, 3)
        self.assertEqual(self.template1.category, self.template2.category)

        self.assertEqual(self.template3.sort_order, 1)
        self.assertEqual(self.template5.sort_order, 2)
        self.assertEqual(self.template3.category, self.template5.category)
        data = {
            'sort_order': 1,
        }
        url = reverse('smstemplate-detail', kwargs={
            'pk': self.template5.pk,
        })
        response = self.george_client.patch(url, data)
        self.assertEqual(response.status_code, 200)
        self.template3.refresh_from_db()
        self.template5.refresh_from_db()
        self.assertEqual(self.template3.sort_order, 2)
        self.assertEqual(self.template5.sort_order, 1)
        self.assertEqual(self.template3.category, self.template5.category)
