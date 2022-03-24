from functools import lru_cache

import simple_salesforce

from django.conf import settings

from ..models.product import Product


class Salesforce(simple_salesforce.Salesforce):
    """ An enhanced Salesforce client with some helper methods for our routine use.

    To get fields from a salesforce endpoint, interrogate from the client, e.g.

    print([f['name'] for f in self.Opportunity.describe()['fields']])

    For more information:
    https://developer.salesforce.com/docs/atlas.en-us.api_rest.meta/api_rest/
    """

    @lru_cache(maxsize=None)
    def get_account_id_from_company_id(self, company_id):
        """ Given a company_id from the ORM, get the underlying SF AccountId.
        Returns SF AccountId.
        Raises simple_salesforce.exceptions.SalesforceResourceNotFound
        """
        return self.Account.get('Sherpa_Company_ID__c/' + str(company_id))['Id']

    def create_account_record_from_company(self, company, bt_subscription=None):
        """ Return a data dictionary formatted as a SF Account record. """

        data = {
            'Name': company.name,
            'BillingStreet': company.billing_address,
            'BillingCity': company.city,
            'BillingState': company.state,
            'BillingPostalCode': company.zip_code,
            # 'Phone': '',
            # 'Website': '',
            'Billing_Account_ID__c': company.braintree_id,
            'Company_Join_Date__c': str(company.created.date()),
            'Monthly_Upload_Limit__c': company.monthly_upload_limit,
            'Monthly_Upload_Count__c': company.monthly_upload_count,
            'Timezone__c': company.timezone,
        }
        if company.invitation_code:
            data['Invitation_Code__c'] = company.invitation_code.code

        # if the company has a subscription and the subscription was provided
        # TODO: this logic is not authoritative... once account+subscription are first class
        # in our system, need to make this be wholly derived from that source
        if bt_subscription and company.subscription_id:
            # we already know our subscriptions are active if they are allowed
            # if subscription.status == braintree.Subscription.Status.Active
            # TODO: introspect
            data['Subscription_Status__c'] = company._meta.model.SubscriptionStatus.ACTIVE
            # subscription_start_date = str(
            #     # NOT doing the following because of discrepencies in data...
            #     # company.subscription_signup_date.date()
            #     # if company.subscription_signup_date else
            #     bt_subscription.first_billing_date
            # )
            # NOTE: the following is not pushable because it is derived from transaction data
            # data['Subscription_Start_Date__c'] = subscription_start_date

            # data['Contract_End_Date__c'] =
            # next_billing_date = str(subscription.next_billing_date)
            # next_billing_period_amount = str(subscription.next_billing_period_amount)
            # billing_period_end_date = str(subscription.billing_period_end_date)
            # billing_period_start_date = str(subscription.billing_period_start_date)

            # if a cancellation request, add those details
            # TODO: review this based on discussion
            cr = company.cancellation_requests.last()
            if cr:
                data.update(**{
                    'Cancel_Request_Date__c': str(
                        cr.request_datetime.date() if cr.request_datetime else '',
                    ),
                    'Cancellation_Status__c': cr.status,
                    'Cancellation_Reason__c': cr.cancellation_reason,
                    'Cancellation_Details__c': cr.cancellation_reason_text,
                    'Cancel_Date__c': str(cr.cancellation_date or ''),
                })
        return data

    def upsert_account_from_company(self, company, bt_subscription=None):
        """ Given a company from the ORM, upsert an Account to Salesforce.
        """
        data = self.create_account_record_from_company(company, bt_subscription)
        # upsert the object to salesforce
        return self.Account.upsert(
            'Sherpa_Company_ID__c/' + str(company.id),
            data,
        )

    def create_contact_record_from_userprofile(self, userprofile):
        """ Return a data dictionary formatted as a SF Contact record. """
        data = {
            'FirstName': userprofile.user.first_name,
            'LastName': userprofile.user.last_name,
            'Phone': userprofile.phone or '',
            'Email': userprofile.user.email,
            'User_Name__c': userprofile.user.username,
            'Join_Date__c': str(userprofile.user.date_joined.date()),
            'Sherpa_Product_Interest__c': ';'.join(
                userprofile.interesting_features.values_list('name', flat=True),
            ),
            'Sherpa_Company_ID__c': userprofile.company_id,
            'Sherpa_App_Role__c': userprofile.role,
        }
        if userprofile.company_id:
            data['AccountId'] = self.get_account_id_from_company_id(userprofile.company_id)
        return data

    def upsert_contact_from_userprofile(self, userprofile):
        """ Given a userprofile from the ORM, upsert a Contact to Salesforce.
        """
        data = self.create_contact_record_from_userprofile(userprofile)
        return self.Contact.upsert(
            'Sherpa_User_ID__c/' + str(userprofile.user_id),
            data,
        )

    @lru_cache(maxsize=None)
    def get_product_from_product_id(self, product_id):
        """ Given a product_id from the ORM, get the underlying SF Product2.
        Returns SF Product2.
        Raises simple_salesforce.exceptions.SalesforceResourceNotFound
        """
        return self.Product2.get_by_custom_id('Product_Line_ID__c', product_id)

    def upsert_opportunity_from_transaction(self, transaction, company_id, bt_subscription=None):
        """ Given a transaction from Braintree, upsert an Opportunity to Salesforce.
        """
        sf_account_id = self.get_account_id_from_company_id(company_id)

        # the transaction was tied to a plan via a subscription or
        # made via API call and indicated on a custom field "type"
        # if the transaction is for an invalid sku, skip it
        sku = (
            transaction.plan_id
            if transaction.plan_id
            else (transaction.custom_fields or {}).get('type')
        )
        primary_product_id = Product.get_id_from_sku(sku)
        products_not_supported = set()
        if not primary_product_id:
            products_not_supported |= {sku}
            return products_not_supported

        created_date = str(transaction.created_at.date())
        name = ' '.join((sf_account_id, created_date, transaction.id))
        transaction_amount = transaction.amount
        data = {
            'Name': name,
            'AccountId': sf_account_id,
            'Amount': str(transaction_amount),
            'CloseDate': created_date,
            'Pricebook2Id': '01s5Y000000TZWTQA4',  # Standard Price Book
            'StageName': 'Closed Won',
            # 'Probability': transaction.name,
            # 'Type': transaction.name,
        }
        self.Opportunity.upsert(
            'Transaction_ID__c/' + str(transaction.id),
            data,
        )

        # deal with line items
        opportunity_id = self.Opportunity.get('Transaction_ID__c/' + str(transaction.id))['Id']

        # deal with add-ons and line items first...
        # we need to deduct them to get the amount paid for the plan
        add_ons_to_post_process = []
        for add_on in transaction.add_ons:
            product_id = Product.get_id_from_sku(add_on.id)
            if not product_id:
                products_not_supported |= {add_on.id}
                continue
            transaction_amount -= add_on.quantity * add_on.amount
            add_ons_to_post_process.append(add_on)

        for line_item in transaction.line_items:
            print(line_item)

        # no special treatment for discount... it comes off the plan

        self.upsert_opportunity_line_item(
            opportunity_id,
            primary_product_id,
            1,
            transaction_amount,
            created_date,
        )

        # we want the add ons to show up as line items 2+
        for add_on in add_ons_to_post_process:
            self.upsert_opportunity_line_item(
                opportunity_id,
                product_id,
                add_on.quantity,
                add_on.amount,
                created_date,
            )

        return products_not_supported

    def upsert_opportunity_line_item(
        self, opportunity_id, product_id, quantity, unit_price, created_date,
    ):
        """ Given an OpportunityId in Salesforce, upsert an Opportunity Line Item.
        """

        product = self.get_product_from_product_id(product_id)

        data = {
            'Quantity': quantity,
            'UnitPrice': str(unit_price),
            'ServiceDate': created_date,
            'Description': product['Description'],
            # 'TotalPrice': str(quantity*unit_price),
        }

        try:
            return self.OpportunityLineItem.update(
                f'LineItemId__c/{opportunity_id}_{product_id}',
                data,
            )
        except simple_salesforce.SalesforceMalformedRequest:
            data['OpportunityId'] = opportunity_id
            data['Product2Id'] = product['Id']
            return self.OpportunityLineItem.upsert(
                f'LineItemId__c/{opportunity_id}_{product_id}',
                data,
            )


def get_salesforce_client() -> Salesforce:
    """ Return a fresh instance of a Salesforce client.

    This is required because for tasks the token will expire on the singleton instance.
    """
    return Salesforce(
        username=settings.SALESFORCE_USERNAME,
        password=settings.SALESFORCE_PASSWORD,
        security_token=settings.SALESFORCE_SECURITY_TOKEN,
        domain=settings.SALESFORCE_DOMAIN,
    )
