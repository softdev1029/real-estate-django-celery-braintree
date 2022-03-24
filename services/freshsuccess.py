import json

import requests

from django.conf import settings


class FreshsuccessClient:
    """
    Client class to handle interactions with freshsuccess.

    In general, the methods here are made to accept any of the endpoint resource types and rely upon
    standard rest practices to perform these actions.

    docs: https://developer.freshsuccess.com/api/apidoc.html
    """
    api_base = 'https://api-us.freshsuccess.com/api/v2'
    api_key = settings.FRESHSUCCESS_API_KEY
    is_production = all([
        settings.USE_TEST_FRESHSUCCESS is False,
        api_key is not None,
        not settings.TEST_MODE,
    ])

    def __init__(self, is_production=False):
        """
        Allow overriding the client to be production.

        :param is_production: Boolean to determine if we should interact with production.
        """
        if is_production:
            self.is_production = is_production

    def __response(self, payload=None):
        """
        Simulate a response from freshsucess for testing purposes.

        :arg payload: dictionary of data to return in the test response payload.
        """
        class FreshsuccessResponse:
            def json(self):
                return payload or {}

        return FreshsuccessResponse()

    def __get_object_id_name(self, resource_type):
        """
        Return the object id field name for the resource type.

        :param resource_type: The resource type that we want to get the object id field name.
        """
        if resource_type == 'accounts':
            return 'account_id'
        elif resource_type == 'account_users':
            return 'user_id'

        raise Exception(f'Received an unknown resource type `{resource_type}`.')

    def __get_resource_url(self, resource_type, object_id=None, nested_resource_type=None,
                           nested_object_id=None):
        """
        Return the full url for interacting with a resource through the freshdesk api.

        :param resource_type: The main resource we're interacting with
        :param object_id: (optional) The id for the resource object
        :param nested_resource_type: (optional) The secondary resource type we're interacting with
        :param nested_object_id: (optional) The id for the secondary resource object.
        """
        url = f'{self.api_base}/{resource_type}'
        if object_id:
            # Append the id for the main resource object.
            url += f'/{object_id}'

        # Tack on the api key.
        return f'{url}?api_key={self.api_key}'

    def __process_payload(self, payload_dict):
        """
        Process the payload so that it's ready to be sent as request data.

        :param payload: dict of data that should be sent in the request.
        """
        return json.dumps(payload_dict)

    def list(self, resource_type):
        """
        List freshsuccess resource objects.

        :param resource_type: string value of the resource endpoint we're working with.
        """
        if not self.is_production:
            return self.__response()

        url = self.__get_resource_url(resource_type)
        return requests.get(url)

    def retrieve(self, resource_type, object_id):
        """
        Retrieve a freshsuccess resource object.

        :param resource_type: string value of the resource endpoint we're working with.
        :param object_id: value of the id for the resource object.
        """
        if not self.is_production:
            return self.__response()

        url = self.__get_resource_url(resource_type, object_id=object_id)
        return requests.get(url)

    def create(self, resource_type, payload):
        """
        Create a freshsuccess resource object.

        :param resource_type: string value of the resource endpoint we're working with.
        :param payload: dictionary of data to pass as the payload.
        """
        if not self.is_production:
            return self.__response({'success': True})

        url = self.__get_resource_url(resource_type)

        # Need to modify the data a bit to prepare to send.
        prepared_payload = {"records": [payload]}
        json_payload = self.__process_payload(prepared_payload)
        return requests.post(url, json_payload)

    def delete(self, resource_type, object_id):
        """
        Delete a freshsuccess resource object.

        :param resource_type: string value of the resource endpoint we're working with.
        :param object_id: value of the id for the resource object.
        """
        if not self.is_production:
            return self.__response({'success': True})

        url = self.__get_resource_url(resource_type, object_id)
        return requests.delete(url)

    def update(self, resource_type, object_id, payload):
        """
        Update a freshsuccess resource object.

        :param resource_type: string value of the resource endpoint we're working with.
        :param object_id: value of the id for the resource object.
        :param payload: dictionary of data to pass as the payload.
        """
        if not self.is_production:
            return self.__response({'success': True})

        object_id_name = self.__get_object_id_name(resource_type)
        url = self.__get_resource_url(resource_type, object_id)

        # Need to always pass in the object id field.
        payload[object_id_name] = object_id
        prepared_payload = {"data": payload}
        json_payload = self.__process_payload(prepared_payload)
        return requests.put(url, json_payload)


def get_dimensions(company):
    """
    Builds the custom field dimensions for Freshsuccess

    :param company Company: The company being managed.
    """
    dimensions = [
        {
            'dimension_type': 'value',
            'source_property_name': 'days_since_last_qualified_lead',
        },
        {
            'dimension_type': 'value',
            'source_property_name': 'prospect_upload_percent',
        },
        {
            'dimension_type': 'value',
            'source_property_name': 'days_until_subscription_renewal',
        },
        {
            'dimension_type': 'value',
            'source_property_name': 'days_since_last_batch_started',
        },
        {
            'dimension_type': 'value',
            'source_property_name': 'real_estate_experience_rating',
        },
        {
            'dimension_type': 'value',
            'source_property_name': 'monthly_upload_limit',
        },
        {
            'dimension_type': 'date',
            'source_property_name': 'subscription_start_date',
        },
        {
            'dimension_type': 'label',
            'source_property_name': 'subscription_status',
        },
    ]

    if company.invitation_code:
        dimensions.append(
            {
                'dimension_type': 'label',
                'source_property_name': 'code',
                'source_subobj': company.invitation_code,
                'fs_dimension_name': 'Invitation Code',
            },
        )

    if company.telephonyconnection_set.filter(provider='twilio').exists():
        dimensions.append(
            {
                'dimension_type': 'label',
                'source_property_name': 'provider',
                'source_subobj': company.telephonyconnection_set.filter(provider='twilio').first(),
                'fs_dimension_name': 'Telephony Provider',
            },
        )

    # There are also some dimensions that need to be added if the company has a cancellation request
    if company.last_cancellation:
        cancellation_dimensions = [
            {
                'dimension_type': 'date',
                'source_property_name': 'request_datetime',
                'source_subobj': company.last_cancellation,
                'fs_dimension_name': 'Cancellation Request Date',
            },
            {
                'dimension_type': 'date',
                'source_property_name': 'cancellation_date',
                'source_subobj': company.last_cancellation,
                'fs_dimension_name': 'Cancellation Date',
            },
            {
                'dimension_type': 'label',
                'source_property_name': 'cancellation_reason',
                'source_subobj': company.last_cancellation,
                'fs_dimension_name': 'Cancellation Reason',
            },
            {
                'dimension_type': 'label',
                'source_property_name': 'cancellation_reason_text',
                'source_subobj': company.last_cancellation,
                'fs_dimension_name': 'Cancellation Reason Text',
            },
            {
                'dimension_type': 'label',
                'source_property_name': 'status',
                'source_subobj': company.last_cancellation,
                'fs_dimension_name': 'Cancellation Status',
            },
        ]
        dimensions += cancellation_dimensions
    if company.campaign_set.filter(is_direct_mail=True).exists():
        direct_email_dimensions = [
            {
                'dimension_type': 'value',
                'source_property_name': 'total_direct_mail_count',
                'fs_dimension_name': 'Total Direct Mail Campaign Count',
            },
            {
                'dimension_type': 'date',
                'source_property_name': 'latest_dm_create_date',
                'fs_dimension_name': 'Latest Direct Mail Campaign Created Date',
            },
        ]
        dimensions += direct_email_dimensions
    return dimensions
