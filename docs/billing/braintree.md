Braintree
=========

Braintree is used as the billing provider in the system.  It is premised on subscription-based
transactions and so it is optimized for that use case.  Initial setup involves establishing
Plans, Add-ons, and Discounts.  Customers and their Payment Methods are then added.  Finally,
one-off transactions can be made on behalf of the customer, or recurring transactions tied to
a subscription can be used.  We have made table space for the following so far:

- BTPlan
- BTAddon
- BTDiscount
- BTTransaction
- BTTransactionStatus

A definite need is a complete copy of the BT Subscription, and a thin BT Customer model to join
our Company/User with the Customer in Braintree.

Braintree must be the source of truth for Plans, Addons, and Discounts because of its design.
These objects can only be created there.  Ideally, Customers, Subscriptions, and Transactions
are all managed by the app, but there will be some reconciliation to do there.

There are currently 27 product lines, of which 16 are legacy.  There is filtering logic in place
that narrows pulls from Braintree to the allowed 11 SKUs, which are basically 5 plans and 6 addons.

https://www.braintreegateway.com/merchants/3sm6qt24mfcgmt34/plans?page=3
