from datetime import date

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.sites.models import Site
from django.db import transaction
from django.utils import timezone

from billing.models import Transaction
from core import models
from properties.utils import get_or_create_address
from sherpa.tasks import sherpa_send_email
from ..directmail import DirectMailProvider
from ..directmail_clients import DirectMailOrderStatus, DirectMailResponse, DirectMailStatusResponse
from ..managers import DirectMailCampaignManager
from ..utils import get_dm_charges

User = get_user_model()


class DirectMailCampaign(models.Model):
    """
    Model for Direct Mail Campaigns.
    """
    provider = models.CharField(max_length=255, choices=DirectMailProvider.CHOICES)
    campaign = models.OneToOneField(
        'sherpa.Campaign',
        on_delete=models.CASCADE,
        related_name='directmail',
    )
    dm_campaign_stats = models.OneToOneField(
        'campaigns.DirectMailCampaignStats',
        blank=True,
        null=True,
        on_delete=models.SET_NULL,
        related_name='dm_campaign',
    )
    return_address = models.ForeignKey(
        'campaigns.DirectMailReturnAddress',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    order = models.ForeignKey(
        'campaigns.DirectMailOrder',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )
    budget_per_order = models.DecimalField(default=0, decimal_places=2, max_digits=10)
    is_locked = models.BooleanField(default=False)
    reminder_sent = models.BooleanField(default=False)  # Warning for lock remiander email sent
    dm_transaction = models.ForeignKey(
        'billing.Transaction', null=True, blank=True, on_delete=models.CASCADE)
    is_draft = models.BooleanField(default=False)

    objects = DirectMailCampaignManager()

    @property
    def prospects(self):
        """
        `Prospects` in this `Campaign`.
        """
        return self.campaign.prospects

    @property
    def total_recipients(self):
        """
        Returns a count of total recipients that will be sent the mail.
        """
        return self.prospects.count()

    @property
    def __client(self):
        """
        Client based on provider.
        """
        return DirectMailProvider.CLIENTS[self.provider]

    @property
    def __formatted_records(self):
        """
        Formatted records based on provider.
        """
        return DirectMailProvider.FORMATTER[self.provider](
            self.prospects,
            self.return_address,
        )

    @property
    def template_options(self):
        """
        Valid template options for provider.
        """
        return DirectMailProvider.TEMPLATES[self.provider]

    @property
    def cost(self):
        """
        DM Campaign cost with or without discount.
        """
        postcard_price = get_dm_charges(company=self.campaign.company,
                                        drop_date=self.order.drop_date)
        return int(self.total_recipients) * postcard_price

    @property
    def should_auth_and_lock(self):
        """
        Determines if the DirectMail order on the campaign is allowed to authorize and lock.
        """
        current_date = timezone.now()
        check_on_date = (current_date + timezone.timedelta(days=3)).date()
        return self.order.drop_date <= check_on_date

    @property
    def order_name(self):
        return f'{self.campaign.company.name} - {self.campaign.pk}'

    def attempt_auth_and_lock(self):
        """
        Will attempt to authorize and lock the DirectMail order if the drop date is within
        range.
        """
        if self.should_auth_and_lock:
            self.order.auth_and_lock_order()

    def attempt_charge_campaign(self):
        """
        Attempts to charge the locked DM campaign if the company is not billing exempt.
        """
        if not self.is_locked:
            # Only attempt to charge locked campaigns.
            return False
        if self.campaign.company.is_billing_exempt:
            # Only attempt to charge campaigns with non billing exempt companies.
            return True
        if not self.dm_transaction:
            # If we get this far and there is no transaction, return False.
            return False
        if self.dm_transaction.is_charged:
            return True

        total_prospect = self.campaign.total_prospects
        price_per_piece = get_dm_charges(company=self.campaign.company,
                                         drop_date=self.order.drop_date)
        amount_to_be_charged = int(total_prospect) * price_per_piece
        self.dm_transaction.charge(amount_to_be_charged)
        return self.dm_transaction.is_charged

    def setup_return_address(self, user, street, city, state, zipcode, phone):
        """
        Setup return address.
        """
        if not (isinstance(user, User) or (user['first_name'] and user['last_name'])):
            raise Exception("user param must be a `User` or have first_name and last_name.")

        user_data = user if not(isinstance(user, User)) else user.__dict__

        address = get_or_create_address({
            'street': street,
            'city': city,
            'state': state,
            'zip': zipcode,
        })
        self.return_address, _ = DirectMailReturnAddress.objects.get_or_create(
            from_user=user if isinstance(user, User) else None,
            first_name=user_data['first_name'],
            last_name=user_data['last_name'],
            address=address,
            phone=phone,
        )
        self.save(update_fields=['return_address'])

    def setup_order(self, drop_date: date, template: str, creative_type: str, note: str):
        """
        Setup pending order.
        """
        if template not in [x[0] for x in self.template_options]:
            raise Exception(f"{template} is not valid for {self.provider}")

        self.order = DirectMailOrder.setup_pending_order(drop_date, template, creative_type, note)
        self.save(update_fields=['order'])

    def push_to_print(self):
        """
        Push formatted records to API client.
        """
        if not self.order:
            raise Exception('Order does not exist')

        response = self.__client.upload(
            self.__formatted_records,
            self.order.template,
            self.order.drop_date.strftime('%Y-%m-%d'),
            self.order.note_for_processor,
            self.order_name,
        )
        self.order.update_from_direct_mail_response(response)

    def get_order(self):
        """
        Get order from API client.
        """
        if not self.order:
            raise Exception('Order does not exist')

        response = self.__client.get_order(self.order.order_id)
        self.order.update_from_direct_mail_response(response)

    def cancel_order(self):
        # We can only cancel dm campaigns before they are locked or processing
        if self.is_locked or self.order.status != DirectMailOrderStatus.SCHEDULED:
            raise ValueError("Can't cancel order")

        self.order.status = DirectMailOrderStatus.CANCELLED
        self.order.save(update_fields=["status"])


class DirectMailReturnAddress(models.Model):
    """
    Model for Return Address to use for Direct Mail
    """
    from_user = models.ForeignKey(User, null=True, blank=True, on_delete=models.CASCADE)
    first_name = models.CharField(null=True, blank=True, max_length=255)
    last_name = models.CharField(null=True, blank=True, max_length=255)
    address = models.ForeignKey('properties.Address', on_delete=models.CASCADE)
    phone = models.CharField(null=True, blank=True, max_length=255)

    def update(self, user=None, street=None, city=None, state=None, zipcode=None, phone=None):
        """
        Update return address.
        """
        update_fields = []
        if not (user or street or city or state or phone):
            return

        if user:
            self.__update_user(user)

        if phone:
            self.phone = phone
            update_fields.append('phone')

        if street or city or state or zipcode:
            address = get_or_create_address({
                'street': street if street else self.address.address,
                'city': city if city else self.address.city,
                'state': state if state else self.address.state,
                'zip': zipcode if zipcode else self.address.zip_code,
            })
            self.address = address
            update_fields.append('address')

        self.save(update_fields=update_fields)

    def __update_user(self, user):
        """
        Update user data.
        """
        if not user:
            return
        if not (isinstance(user, User) or (user['first_name'] and user['last_name'])):
            raise Exception("user param must be a `User` or have first_name and last_name.")

        user_data = user if not (isinstance(user, User)) else user.__dict__
        self.from_user = user
        self.first_name = user_data['first_name']
        self.last_name = user_data['last_name']

        self.save(update_fields=['from_user', 'first_name', 'last_name'])


class DirectMailOrder(models.Model):
    """
    Model for Direct Mail Orders
    """
    order_id = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        choices=DirectMailOrderStatus.CHOICES,
        default=DirectMailOrderStatus.SCHEDULED,
    )
    error = models.CharField(max_length=255, blank=True, null=True)
    record_count = models.IntegerField(default=0)
    drop_date = models.DateField(null=True, blank=True)
    scheduled_date = models.DateField(auto_now_add=True)
    template = models.CharField(max_length=255, blank=True, null=True)
    creative_type = models.CharField(default="postcard", max_length=100)
    received_by_print_date = models.DateField(null=True, blank=True)  # Yellowletter response
    in_production_date = models.DateField(null=True, blank=True)  # Yellowletter response
    in_transit_date = models.DateField(null=True, blank=True)  # Accuzip response
    processed_for_delivery_date = models.DateField(null=True, blank=True)  # Accuzip response
    delivered_date = models.DateField(null=True, blank=True)  # Accuzip response
    note_for_processor = models.TextField(blank=True, null=True)
    tracking_url = models.CharField(max_length=255, blank=True, null=True)
    tracking_job_id = models.CharField(max_length=50, blank=True, null=True)
    tracking_stats = models.ForeignKey(
        'campaigns.DirectMailTracking',
        blank=True,
        null=True,
        on_delete=models.CASCADE,
    )

    @staticmethod
    def setup_pending_order(drop_date: date, template: str, creative_type: str, note: str):
        """
        Create new `DirectMailOrder` from `DirectMailResponse`.
        """
        return DirectMailOrder.objects.create(
            drop_date=drop_date,
            template=template,
            creative_type=creative_type,
            note_for_processor=note,
        )

    @property
    def total_delivered(self):
        """
        Count of total delivered successfully.
        """
        return self.__get_count_by_status(DirectMailTrackingByPiece.Status.DELIVERED)

    @property
    def total_returned(self):
        """
        Count of total returned.
        """
        return self.__get_count_by_status(DirectMailTrackingByPiece.Status.RETURNED)

    @property
    def total_redirected(self):
        """
        Count of total redirected.
        """
        return self.__get_count_by_status(DirectMailTrackingByPiece.Status.REDIRECTED)

    def __get_count_by_status(self, status):
        """
        Return count of mail pieces by status.
        """
        return self.directmailtrackingbypiece_set.filter(status=status).count()

    @property
    def delivered_rate(self):
        """
        Calculate rate of total delivered successfully.
        """
        return self.__rate_for_total(self.total_delivered)

    @property
    def returned_rate(self):
        """
        Calculate rate of total returned.
        """
        return self.__rate_for_total(self.total_returned)

    @property
    def redirected_rate(self):
        """
        Calculate rate of total redirected.
        """
        return self.__rate_for_total(self.total_redirected)

    def __rate_for_total(self, total):
        """
        Calculate rate for given total against total records.
        """
        if not self.record_count:
            return 0

        return round(total / self.record_count, 2)

    @property
    def __client(self):
        """
        Client based on provider.
        """
        return DirectMailProvider.TRACKING_CLIENTS

    @property
    def dm_campaign(self):
        return self.directmailcampaign_set.get()

    @property
    def campaign(self):
        return self.dm_campaign.campaign

    @property
    def is_printing(self):
        """
        Boolean indicating if status is in the printing stage
        """
        return DirectMailOrderStatus.is_printing(self.status)

    def setup_tracking(self, job_id, tracking_url, imd, barcode):
        """
        Setup so we can get tracking data by campaign and by piece.
        """
        if not self.tracking_url or not self.tracking_job_id:
            self.tracking_job_id = job_id
            self.tracking_url = tracking_url
            self.save(update_fields=['tracking_job_id', 'tracking_url'])

        # TODO: Add this back when Yellow Letter starts sending imd & barcode
        # tracking, _ = DirectMailTrackingByPiece.get_or_create(imd=imd,
        # barcode=barcode, order=self)

    def update_status(self):
        """
        Get tracking status.
        """
        if not self.tracking_url or self.is_printing:
            self.dm_campaign.get_order()
            return

        response = self.__client.get_status(self.tracking_url)

        if not self.tracking_stats:
            self.tracking_stats = DirectMailTracking.objects.create()
            self.save(update_fields=['tracking_stats'])

        complete = self.tracking_stats.update_from_direct_mail_response(response)
        if complete:
            from ..tasks import send_campaign_complete_email
            send_campaign_complete_email.delay(self.campaign.id)

        self.update_status_on_tracking_thresholds()
        # TODO: Uncomment when Yellow Letter sends imd & barcode
        # self.get_stats_by_piece()

    def get_stats_by_piece(self):
        """
        Get stats by piece by status.
        """
        delivered = self.__client.get_delivered(self.tracking_job_id)
        self.update_stats_by_piece(delivered.data, DirectMailTrackingByPiece.Status.DELIVERED)
        returned = self.__client.get_returned(self.tracking_job_id)
        self.update_stats_by_piece(returned.data, DirectMailTrackingByPiece.Status.RETURNED)
        redirected = self.__client.get_redirected(self.tracking_job_id)
        self.update_stats_by_piece(redirected.data, DirectMailTrackingByPiece.Status.REDIRECTED)

        if delivered.error or redirected.error or returned.error:
            error = f"Error getting delivered: {delivered.error}, " \
                    f"Error getting redirected: {redirected.error} " \
                    f"Error getting returned: {returned.error}"
            self.error = error
            self.save(update_fields=['error'])

    def update_stats_by_piece(self, records, status):
        """
        Update stats by piece.

        :records: list of dict with imb & barcode
        :status: status to update record with (DirectMailTrackingByPiece.Status)
        """
        for record in records:
            tracking, _ = DirectMailTrackingByPiece.get_or_create(
                tracking_imb=record['imb'],
                tracking_barcode=record['barcode'],
                order=self,
                status=status,
            )

    def update_status_on_tracking_thresholds(self):
        """
        Update status based on tracking status hitting certain thresholds.
        """
        if self.tracking_stats.delivered_threshold:
            self.status = DirectMailOrderStatus.COMPLETE
            self.save(update_fields=['status'])
        elif self.tracking_stats.en_route_threshold:
            self.status = DirectMailOrderStatus.OUT_FOR_DELIVERY
            self.save(update_fields=['status'])

    def update_from_direct_mail_response(self, response: DirectMailResponse):
        """
        Update from `DirectMailResponse`.
        """
        self.order_id = response.order_id if response.order_id else self.order_id
        self.status = response.status if response.status else self.status
        self.record_count = response.record_count if response.record_count else self.record_count
        self.drop_date = response.drop_date if response.drop_date else self.drop_date
        self.template = response.template if response.template else self.template
        self.error = response.error
        self.save()

    def auth_and_lock_order(self):
        with transaction.atomic():
            dm_camp = DirectMailCampaign.objects.get(order=self)
            campaign = dm_camp.campaign
            site = Site.objects.get(id=settings.DJOSER_SITE_ID)
            mail_subject = f"Your Direct Mail Campaign {campaign.name} is now locked"
            sherpa_send_email(
                mail_subject,
                'email/direct_mail/lock_mail.html',
                campaign.created_by.email,
                {
                    'site': site,
                    'campaign_name': campaign.name,
                    'campaign_id': campaign.id,
                    'drop_date': self.drop_date.strftime('%Y-%m-%d'),
                },
            )
            dm_camp.is_locked = True
            self.status = DirectMailOrderStatus.LOCKED
            self.save(update_fields=['status'])
            update_fields = ['is_locked']
            if not dm_camp.campaign.company.is_billing_exempt:
                if dm_camp.dm_transaction is None or not dm_camp.dm_transaction.is_authorized:
                    update_fields.append('dm_transaction')
                    total_prospect = dm_camp.campaign.total_prospects
                    price_per_piece = get_dm_charges(company=dm_camp.campaign.company,
                                                     drop_date=self.drop_date)
                    amount_to_be_charged = int(total_prospect) * price_per_piece
                    dm_camp.dm_transaction = Transaction.authorize(
                        campaign.company,
                        'Direct mail fee',
                        amount_to_be_charged,
                    )
                if not dm_camp.dm_transaction.is_authorized:
                    sherpa_send_email(
                        'Authorization Failed',
                        'email/email_direct_email_transaction_failed.html',
                        campaign.created_by.email,
                        {
                            'site': site,
                            'campaign_name': campaign.name,
                            'campaign_id': campaign.id,
                            'drop_date': self.drop_date.strftime('%Y-%m-%d'),
                        },
                    )
                    self.status = DirectMailOrderStatus.INCOMPLETE
                    self.save(update_fields=['status'])
            dm_camp.save(update_fields=update_fields)


class DirectMailTracking(models.Model):
    """
    Model to hold Direct Mail tracking information.
    """
    record_count = models.IntegerField(default=0)
    not_scanned = models.IntegerField(default=0)
    early = models.IntegerField(default=0)
    on_time = models.IntegerField(default=0)
    late = models.IntegerField(default=0)
    en_route = models.IntegerField(default=0)
    total_undelivered = models.IntegerField(default=0)
    error = models.CharField(max_length=255, blank=True, null=True)

    @property
    def total_delivered(self):
        """
        Calculate count of total delivered successfully.
        """
        return self.early + self.on_time + self.late

    @property
    def delivery_rate(self):
        """
        Calculate rate of total delivered successfully.
        """
        if not self.record_count:
            return 0

        return round(self.total_delivered / self.record_count, 2)

    @property
    def undeliverable_rate(self):
        """
        Calculate rate of total that failed to deliver.
        """
        if not self.record_count:
            return 0

        return round(self.total_undelivered / self.record_count, 2)

    @property
    def percent_en_route(self):
        """
        Percent en route or out for delivery
        """
        if not self.record_count:
            return 0

        return round(self.en_route / self.record_count, 2)

    @property
    def en_route_threshold(self):
        """
        Indicate if order has met en route threshold
        """
        return self.percent_en_route >= .75

    @property
    def delivered_threshold(self):
        """
        Indicate if order has met delivered threshold
        """
        return self.delivery_rate >= .5

    def update_from_direct_mail_response(self, response: DirectMailStatusResponse):
        """
        Update from `DirectMailStatusResponse`.
        :return bool: Indicates if all mail pieces have been delivered.
        """
        self.record_count = response.record_count if response.record_count else self.record_count
        self.not_scanned = response.not_scanned if response.not_scanned else self.not_scanned
        self.early = response.early if response.early else self.early
        self.error = response.error
        self.on_time = response.on_time if response.on_time else self.on_time
        self.late = response.late if response.late else self.late
        self.en_route = response.en_route if response.en_route else self.en_route
        self.save()

        if self.total_delivered == self.record_count:
            return True
        return False


class DirectMailTrackingByPiece(models.Model):
    """
    Model to track Direct Mail stats by Piece
    """

    class Status:
        RETURNED = 'returned'
        REDIRECTED = 'redirected'
        DELIVERED = 'delivered'

        CHOICES = (
            (RETURNED, 'Returned'),
            (REDIRECTED, 'Redirected'),
            (DELIVERED, 'Delivered'),
        )

    order = models.ForeignKey('campaigns.DirectMailOrder', on_delete=models.CASCADE)
    tracking_imb = models.CharField(max_length=255, blank=True, null=True)
    tracking_barcode = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=50, blank=True, null=True, choices=Status.CHOICES)
