from functools import lru_cache
import logging

import braintree

from django.conf import settings

from ..models.product import Product

logger = logging.getLogger(__name__)

allowed_skus = set(Product.id_mapping.keys())


class BraintreeGateway(braintree.BraintreeGateway):
    """ An enhanced Braintree gateway with some helper methods for our routine use.

    For more information:
    https://developer.paypal.com/braintree/docs/reference/general/best-practices
    """

    @lru_cache(maxsize=None)
    def get_plans(self):
        """ Return a dict of BT Plan IDs mapped to BT Plan response objects. """
        return {
            plan.id: plan
            for plan in gateway.plan.all()
        }

    @lru_cache(maxsize=None)
    def get_allowed_plans(self):
        """ Return a dict of allowed BT Plan IDs mapped to BT Plan response objects. """
        all_plans = self.get_plans()
        allowed_plans = dict()
        for plan in all_plans.values():
            if plan.id in allowed_skus:
                allowed_plans[plan.id] = plan
        plan_ids_not_allowed = set(all_plans.keys()) - set(allowed_plans.keys())
        logger.info(f'Plans processed: {allowed_plans.keys()}')
        logger.warning(f'[ch15557] Plans not processed: {plan_ids_not_allowed}')
        return allowed_plans

    @lru_cache(maxsize=None)
    def get_add_ons(self):
        """ Return a dict of BT AddOn IDs mapped to BT AddOn response objects. """
        return {
            add_on.id: add_on
            for add_on in gateway.add_on.all()
        }

    @lru_cache(maxsize=None)
    def get_allowed_add_ons(self):
        """ Return a dict of allowed BT AddOn IDs mapped to BT AddOn response objects. """
        all_add_ons = self.get_add_ons()
        allowed_add_ons = dict()
        for add_on in all_add_ons.values():
            if add_on.id in allowed_skus:
                allowed_add_ons[add_on.id] = add_on
        add_on_ids_not_allowed = set(all_add_ons.keys()) - set(allowed_add_ons.keys())
        logger.info(f'Add-ons processed: {allowed_add_ons.keys()}')
        logger.warning(f'[ch15557] Add-ons not processed: {add_on_ids_not_allowed}')
        return allowed_add_ons

    @lru_cache(maxsize=None)
    def get_discounts(self):
        """ Return a dict of BT Discount IDs mapped to BT Discount response objects. """
        return {
            discount.id: discount
            for discount in gateway.discount.all()
        }

    @lru_cache(maxsize=None)
    def get_allowed_discounts(self):
        """ Return a set of discount_ids allowed from the full list on BT. """
        discounts_not_processed = self.get_discounts()
        logger.warning(f'[ch15557] Discounts not processed: {discounts_not_processed.keys()}')
        return dict()

    def get_subscriptions(self, *filter_criteria):
        """
        Return an iterator of BT subscription responses.
        """
        return gateway.subscription.search(*filter_criteria)

    def get_plan_subscriptions(self, plan_ids, *filter_criteria):
        """
        plan_ids: list of plan SKUs
        """
        return self.get_subscriptions(
            braintree.SubscriptionSearch.plan_id.in_list([plan_id for plan_id in plan_ids]),
            *filter_criteria,
        )

    def get_active_plan_subscriptions(self, *filter_criteria):
        """ Warning: caching does not work with BT filter criteria. """
        allowed_plan_ids = self.get_allowed_plans().keys()
        ret = self.get_plan_subscriptions(
            allowed_plan_ids,
            braintree.SubscriptionSearch.status == braintree.Subscription.Status.Active,
        )
        return ret

    @lru_cache(maxsize=None)
    def get_active_plan_subscription_ids(self):
        """ Warning: caching does not work with BT filter criteria. """
        return self.get_active_plan_subscriptions().ids

    @lru_cache(maxsize=None)
    def get_subscription(self, subscription_id):
        """ Return a BT Subscription given an BT subscription_id. """
        if subscription_id not in self.get_active_plan_subscription_ids():
            return None
        return self.subscription.find(subscription_id)

    def get_transactions(self, *search_criteria):
        return self.transaction.search(*search_criteria)

    def get_settled_transactions_for_date(self, date, *search_criteria):
        return self.get_transactions(
            braintree.TransactionSearch.settled_at.between(
                date.strftime('%m/%d/%Y 00:00'),
                date.strftime('%m/%d/%Y 23:59'),
            ),
            *search_criteria,
        )


gateway = Gateway = BraintreeGateway(
    braintree.Configuration(
        settings.BRAINTREE_ENV,
        merchant_id=settings.BRAINTREE_MERCHANT_ID,
        public_key=settings.BRAINTREE_PUBLIC_KEY,
        private_key=settings.BRAINTREE_PRIVATE_KEY,
    ),
)
