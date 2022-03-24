from smartystreets_python_sdk import Batch, ClientBuilder, StaticCredentials
from smartystreets_python_sdk.exceptions import SmartyException
from smartystreets_python_sdk.us_street import Lookup

from properties.models import PropertyTag, PropertyTagAssignment


class SmartyClient:
    """
    Smarty streets is used to validate addresses.
    """
    def __init__(self):
        auth_id = '1b2b2960-6998-13c6-fcaa-89bbd2b4671d'
        auth_token = 'F7Z14WFGeX8LyKKnc1YT'
        credentials = StaticCredentials(auth_id, auth_token)
        self.client = ClientBuilder(credentials).build_us_street_api_client()
        self.batch = Batch()
        self.error = None
        self.index = 0

    def send_batch(self):
        """
        Send batch to Smarty Streets
        """
        try:
            self.client.send_batch(self.batch)
        except SmartyException as err:
            self.error = err

    def add_lookup(self, street, city, state, zip_code, input_id=None):
        """
        Add lookup to batch to send to smarty streets.
        """
        self.batch.add(Lookup())
        self.batch[self.index].input_id = input_id
        if street and city and state and zip:
            self.batch[self.index].street = f"{street}, {city} {state} {zip_code}"
        elif street and zip_code:
            self.batch[self.index].street = street
            self.batch[self.index].zipcode = zip_code
        elif street and city and state:
            self.batch[self.index].street = street
            self.batch[self.index].city = city
            self.batch[self.index].state = state
        else:
            # Add invalid address since we're expecting two addresses regardless.
            self.batch[self.index].street = "Invalid Address"

        self.index += 1


smarty_client = SmartyClient().client


class SmartyValidateAddresses(SmartyClient):
    """
    Validate addresses using Smarty Streets.
    """
    def __init__(self, address_object, has_submitted_prefix=True, is_property=False):
        """
        'address_object' is the object you want to save the addresses to.
        'has_submitted_prefix' indicates if the original address in 'address_object' starts with
         'submitted_'
        """
        self.address_object = address_object
        self.is_bulk = isinstance(self.address_object, list)
        self.has_submitted_prefix = has_submitted_prefix
        self.is_property = is_property
        self.address_types = ['mailing', 'property'] if not self.is_property else ['address']
        self.zipcode = 'zip' if not self.is_property else 'zip_code'
        self.results = dict()
        super().__init__()

    def validate_addresses(self):
        """
        Create batch and send to Smarty Streets to validate.
        """
        bulk_addresses = self.address_object if self.is_bulk else [self.address_object]

        for address in bulk_addresses:
            self.__build_lookup(address)

        self.send_batch()
        if not self.error:
            self.save_validated_addresses()

    def __get_address_obj(self, address=None):
        """
        Return address from address object.
        """
        address = address if address else self.address_object
        return address if not self.is_property else address.address

    def __build_lookup(self, address):
        """
        Add address info to lookup for each address type.
        """
        for address_type in self.address_types:
            params = self.__get_address(address, address_type)
            self.add_lookup(*params)

    def __clean_pk(self, pk):
        """
        Convert pk to int
        """
        try:
            pk = int(pk)
            return pk
        except ValueError:
            self.error = f'Invalid pk {pk}'
            return None

    def save_validated_addresses(self):
        """
        Save validated addresses from smarty streets results.
        """
        try:
            update_addresses = self.address_object if self.is_bulk else [self.address_object]
            update_fields = set() if self.is_property else {
                'validated_property_status',
                'validated_mailing_status',
            }
            # Initialize status as 'invalid' because we won't have any connection back to the
            # record if the address is actually invalid.
            if not self.is_property:
                for address in update_addresses:
                    for address_type in self.address_types:
                        self.__add_address_status_to_results(
                            address.pk,
                            address_type,
                            'invalid',
                        )

            for i, lookup in enumerate(self.batch):
                validated_addresses = lookup.result
                if not validated_addresses:
                    continue

                validated_address = validated_addresses[0]
                pk, address_type = validated_address.input_id.split("-")
                pk = self.__clean_pk(pk)
                if not pk:
                    continue

                self.__add_address_status_to_results(pk, address_type, 'validated')

                validated_address_schema = [
                    {
                        'object': validated_address,
                        'fields': ['delivery_line_1', 'delivery_line_2', 'last_line'],
                    },
                    {
                        'object': validated_address.components,
                        'fields': [
                            'primary_number',
                            'street_name',
                            'street_predirection',
                            'street_postdirection',
                            'street_suffix',
                            'secondary_number',
                            'secondary_designator',
                            'extra_secondary_number',
                            'extra_secondary_designator',
                            'pmb_designator',
                            'pmb_number',
                            'city_name',
                            'default_city_name',
                            'state_abbreviation',
                            'zipcode',
                            'plus4_code',
                        ],
                    },
                    {
                        'object': validated_address.metadata,
                        'fields': [
                            'latitude',
                            'longitude',
                            'precision',
                            'time_zone',
                            'utc_offset',
                        ],
                    },
                    {
                        'object': validated_address.analysis,
                        'fields': ['vacant'],
                    },
                ]

                for section in validated_address_schema:
                    update_fields.update(
                        self.update_validated_address_fields(
                            section['fields'],
                            section['object'],
                            address_type,
                            pk,
                        ),
                    )
            self.__save_address_object(list(update_fields))

        except (IndexError, AttributeError, ValueError) as e:
            self.error = e

    def __add_address_status_to_results(self, pk, address_type, status):
        """
        Add address that has been validated to results to be saved.
        """
        if pk not in self.results:
            self.results[pk] = dict()

        # Initialize status to 'validated' if this isn't a property.
        status_field = f'validated_{address_type}_status'
        update_fields = []
        if not self.is_property:
            self.results[pk][status_field] = status
            if not self.is_bulk:
                setattr(self.address_object, status_field, status)
                update_fields.append(status_field)
        return update_fields

    def __get_address(self, address, address_type):
        """
        Get address fields to add to lookup.
        """
        prefix = ''
        if self.has_submitted_prefix:
            prefix = 'submitted_'

        address = self.__get_address_obj(address)

        input_id = f'{getattr(address, "pk")}-{address_type}'
        address_type = f'{address_type}_' if not self.is_property else ''

        street = getattr(address, f'{prefix}{address_type}address')
        city = getattr(address, f'{prefix}{address_type}city', '')
        state = getattr(address, f'{prefix}{address_type}state', '')
        zip_code = getattr(address, f'{prefix}{address_type}{self.zipcode}', '')

        return [street, city, state, zip_code, input_id]

    def update_validated_address_fields(self, fields, from_obj, address_type, pk):
        """
        Update a set of fields from a given object for `SkipTraceProperty's` validated addresses.
        """
        update_fields = []
        for field in fields:
            val = getattr(from_obj, field, '')
            if field == 'vacant' and address_type != 'mailing':
                self.__tag_vacant(val == 'Y', pk)
            field_name = self.__get_address_object_field(address_type, field)
            if not field_name:
                continue
            if self.address_object and not self.is_bulk:
                setattr(self.__get_address_obj(), field_name, val)
                update_fields.append(field_name)
            self.results[pk][field_name] = val

        return update_fields

    def __save_address_object(self, update_fields):
        """
        Save address_object with fields passed in.
        """
        if self.address_object and not self.is_bulk:
            address = self.address_object
            if self.is_property:
                address = self.address_object.address
            address.save(update_fields=update_fields)

    def __get_company(self):
        """
        Return company in address object.
        """
        if self.is_bulk:
            return self.address_object[0].company

        return self.address_object.company

    def __tag_vacant(self, is_vacant, pk):
        """
        Create vacant tag if property is vacant, remove if no longer vacant.
        """
        prop_id = pk
        if not self.is_property:
            if all((
                    not self.is_bulk,
                    self.address_object,
                    hasattr(self.address_object, "prop") and self.address_object.prop),
                   ):
                prop_id = self.address_object.prop.id
            else:
                return

        tag, _ = PropertyTag.objects.get_or_create(
            company=self.__get_company(),
            name='Vacant',
        )

        if is_vacant:
            PropertyTagAssignment.objects.get_or_create(tag=tag, prop__id=prop_id)
            return

        propertyTagAssignments = PropertyTagAssignment.objects.filter(tag=tag, prop__id=prop_id)
        if propertyTagAssignments.exists():
            propertyTagAssignments.delete()

    def __get_address_object_field(self, address_type, field):
        """
        Return the field for the address object being updated.
        """
        if not self.is_property:
            return f'validated_{address_type}_{field}'

        property_fields = {
            'delivery_line_1': 'address',
            'city_name': 'city',
            'state_abbreviation': 'state',
            'zipcode': 'zip_code',
        }

        if field in property_fields:
            return property_fields[field]

        return None
