# flake8: noqa
from django.conf import settings
from django.db import models
from django.db.models import *



class QuerySet(models.QuerySet):
    """
    Sherpa QuerySet class.
    """
    def readonly(self):
        """
        Returns itself using a randomly selected readonly database.
        """
        if settings.TEST_MODE:
            return self
        
        # TODO: switch to readonly database when rolled out.
        return self.using('default')


class Manager(models.Manager.from_queryset(QuerySet)):
    """
    Sherpa default Manager class.
    """
    pass


class Model(models.Model):
    """
    Sherpa default Model class.
    """
    objects = Manager()

    class Meta:
        abstract = True


del models
