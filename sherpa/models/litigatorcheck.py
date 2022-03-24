from django.db.models import Q

from companies.models import UploadBaseModel
from core import models

__all__ = ('LitigatorCheck', 'UploadLitigatorCheck')


class UploadLitigatorCheck(UploadBaseModel):
    """
    Used by a "public" webpage to check against litigators.

    This feature hasn't recieved attention for over a year. Check with Jason if still being used.
    """
    created_local = models.DateTimeField(null=True, blank=True)
    email_address = models.CharField(null=True, blank=True, max_length=255)
    email_started_confirmation_sent = models.BooleanField(default=False)
    email_completed_sent = models.BooleanField(default=False)
    invitation_code = models.CharField(null=True, blank=True, max_length=64)

    token = models.CharField(null=True, blank=True, max_length=255)
    has_header_row = models.BooleanField(default=True)
    validate_address_last_row_processed = models.IntegerField(default=0)

    fullname_column_number = models.IntegerField(null=True, blank=True)
    first_name_column_number = models.IntegerField(null=True, blank=True)
    last_name_column_number = models.IntegerField(null=True, blank=True)
    street_column_number = models.IntegerField(null=True, blank=True)
    city_column_number = models.IntegerField(null=True, blank=True)
    state_column_number = models.IntegerField(null=True, blank=True)
    zipcode_column_number = models.IntegerField(null=True, blank=True)
    mailing_street_column_number = models.IntegerField(null=True, blank=True)
    mailing_city_column_number = models.IntegerField(null=True, blank=True)
    mailing_state_column_number = models.IntegerField(null=True, blank=True)
    mailing_zipcode_column_number = models.IntegerField(null=True, blank=True)
    email_column_number = models.IntegerField(null=True, blank=True)
    custom_1_column_number = models.IntegerField(null=True, blank=True)
    custom_2_column_number = models.IntegerField(null=True, blank=True)
    custom_3_column_number = models.IntegerField(null=True, blank=True)
    phone_1_number = models.IntegerField(null=True, blank=True)
    phone_2_number = models.IntegerField(null=True, blank=True)
    phone_3_number = models.IntegerField(null=True, blank=True)
    phone_4_number = models.IntegerField(null=True, blank=True)
    phone_5_number = models.IntegerField(null=True, blank=True)
    phone_6_number = models.IntegerField(null=True, blank=True)
    phone_7_number = models.IntegerField(null=True, blank=True)
    phone_8_number = models.IntegerField(null=True, blank=True)
    phone_9_number = models.IntegerField(null=True, blank=True)
    phone_10_number = models.IntegerField(null=True, blank=True)
    phone_11_number = models.IntegerField(null=True, blank=True)
    phone_12_number = models.IntegerField(null=True, blank=True)

    @property
    def total_litigators(self):
        return LitigatorCheck.objects.filter(
            Q(litigator_type='Litigator') | Q(litigator_type='Serial Litigator'),
            upload_litigator_check=self,
        ).count()

    @property
    def total_complainers(self):
        return LitigatorCheck.objects.filter(
            Q(litigator_type='Complainer') | Q(litigator_type='Pre-Litigator'),
            upload_litigator_check=self,
        ).count()

    @property
    def total_associated(self):
        return LitigatorCheck.objects.filter(
            Q(upload_litigator_check=self),
            Q(litigator_type='Associated'),
        ).count()

    @property
    def total_phone_numbers(self):
        return LitigatorCheck.objects.filter(
            Q(upload_litigator_check=self),
        ).count()

    @property
    def total_validated_addresses(self):
        return LitigatorCheck.objects.filter(Q(upload_litigator_check=self),
                                             ~Q(validated_property_status=None),
                                             Q(is_first_record=True)).count()


class LitigatorCheck(models.Model):
    """
    Used by a "public" webpage to check against litigators viewed at /litigator/check/home/.

    Needs an update but some users are still using it.
    """
    class Type:
        LITIGATOR = 'Litigator'
        ASSOCIATED = 'Associated'
        COMPLAINER = 'Complainer'
        SERIAL = 'Serial Litigator'
        PRE = 'Pre-Litigator'

        CHOICES = (
            (LITIGATOR, 'Litigator'),
            (ASSOCIATED, 'Associated'),
            (COMPLAINER, 'Complainer'),
            (SERIAL, 'Serial Litigator'),
            (PRE, 'Pre-Litigator'),
        )

    upload_litigator_check = models.ForeignKey(
        'UploadLitigatorCheck', null=True, blank=True, on_delete=models.CASCADE)

    created = models.DateTimeField(auto_now_add=True)
    fullname = models.CharField(null=True, blank=True, max_length=255)
    first_name = models.CharField(null=True, blank=True, max_length=255)
    last_name = models.CharField(null=True, blank=True, max_length=255)
    phone1 = models.CharField(null=True, blank=True, max_length=255)
    phone2 = models.CharField(null=True, blank=True, max_length=255)
    phone3 = models.CharField(null=True, blank=True, max_length=255)
    mailing_address = models.TextField(null=True, blank=True)
    mailing_city = models.CharField(null=True, blank=True, max_length=255)
    mailing_state = models.CharField(null=True, blank=True, max_length=255)
    mailing_zip = models.CharField(null=True, blank=True, max_length=255)
    property_address = models.TextField(null=True, blank=True)
    property_city = models.CharField(null=True, blank=True, max_length=255)
    property_state = models.CharField(null=True, blank=True, max_length=255)
    property_zip = models.CharField(null=True, blank=True, max_length=255)
    related_record_id = models.CharField(null=True, blank=True, max_length=255)
    is_first_record = models.BooleanField(default=False)
    email = models.CharField(null=True, blank=True, max_length=255)
    custom1 = models.CharField(null=True, blank=True, max_length=255)
    custom2 = models.CharField(null=True, blank=True, max_length=255)
    custom3 = models.CharField(null=True, blank=True, max_length=255)
    litigator_type = models.CharField(null=True, blank=True, max_length=64, choices=Type.CHOICES)
    sort_order = models.IntegerField(default=9)

    validated_property_status = models.CharField(null=True, blank=True, max_length=16)
    validated_property_delivery_line_1 = models.CharField(null=True, blank=True, max_length=255)
    validated_property_delivery_line_2 = models.CharField(null=True, blank=True, max_length=255)
    validated_property_last_line = models.CharField(null=True, blank=True, max_length=255)
    validated_property_primary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_property_street_name = models.CharField(null=True, blank=True, max_length=255)
    validated_property_street_predirection = models.CharField(null=True, blank=True, max_length=16)
    validated_property_street_postdirection = models.CharField(null=True, blank=True, max_length=16)
    validated_property_street_suffix = models.CharField(null=True, blank=True, max_length=16)
    validated_property_secondary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_property_secondary_designator = models.CharField(
        null=True, blank=True, max_length=255)
    validated_property_extra_secondary_number = models.CharField(
        null=True, blank=True, max_length=255)
    validated_property_extra_secondary_designator = models.CharField(
        null=True, blank=True, max_length=255)
    validated_property_pmb_designator = models.CharField(null=True, blank=True, max_length=255)
    validated_property_pmb_number = models.CharField(null=True, blank=True, max_length=255)
    validated_property_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_property_default_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_property_state_abbreviation = models.CharField(null=True, blank=True, max_length=255)
    validated_property_zipcode = models.CharField(null=True, blank=True, max_length=16)
    validated_property_plus4_code = models.CharField(null=True, blank=True, max_length=16)
    validated_property_latitude = models.CharField(null=True, blank=True, max_length=255)
    validated_property_longitude = models.CharField(null=True, blank=True, max_length=255)
    validated_property_precision = models.CharField(null=True, blank=True, max_length=255)
    validated_property_time_zone = models.CharField(null=True, blank=True, max_length=255)
    validated_property_utc_offset = models.CharField(null=True, blank=True, max_length=16)
    validated_property_vacant = models.CharField(null=True, blank=True, max_length=16)

    validated_mailing_status = models.CharField(null=True, blank=True, max_length=16, db_index=True)
    validated_mailing_delivery_line_1 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_mailing_delivery_line_2 = models.CharField(
        null=True, blank=True, max_length=255, db_index=True)
    validated_mailing_last_line = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_primary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_street_name = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_street_predirection = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_street_postdirection = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_street_suffix = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_secondary_number = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_secondary_designator = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_extra_secondary_number = models.CharField(
        null=True, blank=True, max_length=255)
    validated_mailing_extra_secondary_designator = models.CharField(
        null=True, blank=True, max_length=255)
    validated_mailing_pmb_designator = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_pmb_number = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_default_city_name = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_state_abbreviation = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_zipcode = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_plus4_code = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_latitude = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_longitude = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_precision = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_time_zone = models.CharField(null=True, blank=True, max_length=255)
    validated_mailing_utc_offset = models.CharField(null=True, blank=True, max_length=16)
    validated_mailing_vacant = models.CharField(null=True, blank=True, max_length=16)

    @property
    def raw_address_to_validate_type(self):
        # Priorty = Full Address, Street + Zip, Street + City + State
        if all([self.property_address, self.property_city, self.property_state, self.property_zip]):
            return "full_address"
        elif self.property_address and self.property_zip:
            return "address_zip"
        elif self.property_address and self.property_city and self.property_state:
            return "address_city_state"
        else:
            return "no_address"
