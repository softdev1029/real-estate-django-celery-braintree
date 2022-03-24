from random import randint

from core import models


class CarrierApprovedTemplateManager(models.Manager):
    def random(self, company=None):
        """
        Grabs a random verified and active entry from the model or, if provided, the company's
        selected carrier templates.

        :param company Company: Limits choice to company's selected carrier templates.
        """
        if company:
            carrier_templates = company.carrier_templates.all()
        else:
            carrier_templates = self.filter(is_verified=True, is_active=True)
        count = carrier_templates.count()
        if count == 0:
            return self.none()
        random_index = randint(0, count - 1)
        return carrier_templates[random_index]
