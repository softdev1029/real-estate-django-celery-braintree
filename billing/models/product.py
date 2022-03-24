# alternative codes used by various spots in code
# TODO: re-map to all to one code
ADDITIONAL_MARKET = 'additional_market'
ADDITIONAL_PHONE = 'additional_phone'
SMS_STARTER = 'starter'
SMS_CORE = 'core'
SMS_PRO = 'pro'
SMS_ENTERPRISE = 'enterprise'
SMS_SH2000 = 'sh2000'

SMS_SKUS_ACTIVE = [
    SMS_STARTER,
    SMS_CORE,
    SMS_PRO,
    SMS_ENTERPRISE,
]


class Product:
    class SKU:
        SUBSCRIPTION = 'subscription fee'
        SKIP_TRACE = 'skip trace fee'
        SHERPA_CREDITS = 'credits fee'
        PHONE_PURCHASE = 'phone purchase'
        UPLOAD = 'upload fee'
        OTHER = 'other'
        MARKET = 'market'
        UNKNOWN = 'unknown'
        DIRECT_MAIL = 'Direct mail fee'

        CHOICES = (
            (SUBSCRIPTION, 'Subscription'),
            (SKIP_TRACE, 'Skip Trace'),
            (SHERPA_CREDITS, 'Sherpa Credits'),
            (UPLOAD, 'Upload'),
            (OTHER, 'Other'),
            (MARKET, 'Market'),
            (UNKNOWN, 'Unknown'),
            (PHONE_PURCHASE, 'Phone Purchase'),
            (DIRECT_MAIL, 'Direct mail fee'),
        )

    # ~ideal
    # id_mapping = {
    #     'sms_starter': 1,
    #     'sms_core': 2,
    #     'sms_pro': 3,
    #     'sms_enterprise': 4,
    #     'sms_market': 5,
    #     'sms_number_telnyx': 6,
    #     'sms_prospect_overage': 7,
    #     'skiptrace_bulk': 8,
    #     'skiptrace_credit': 9,
    #     'directmail_postcard': 10,
    # }

    id_mapping = {
        SMS_STARTER: 1,
        SMS_CORE: 2,
        SMS_PRO: 3,
        SMS_ENTERPRISE: 4,
        ADDITIONAL_MARKET: 5,
        ADDITIONAL_PHONE: 6,
        SKU.MARKET: 5,
        SKU.PHONE_PURCHASE: 6,
        SKU.UPLOAD: 7,
        SKU.SKIP_TRACE: 8,
        SKU.SHERPA_CREDITS: 9,
        SKU.DIRECT_MAIL: 10,
    }

    @staticmethod
    def get_id_from_sku(sku):
        """ Given a SKU, return the ID on Salesforce or None. """
        return Product.id_mapping.get(sku)
