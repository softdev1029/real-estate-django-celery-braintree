from django.utils import timezone
from django.db import transaction
from django.db.models import F
from rest_framework.decorators import action
from rest_framework.mixins import UpdateModelMixin
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from companies.models import DownloadHistory
from sherpa.renderers import ZipRenderer
from sherpa.utils import build_csv


class UpdateWithoutPatchModelMixin(object):
    """
    Mixin for usage in GenericViewSets to allow updating whole objects,
    without allowing partial updates. This is due to an error in the OpenAPI yaml
    file generation process in DRF. Should be fixed in next version (current 3.10.3)
    See PR below for details
    https://github.com/encode/django-rest-framework/pull/6944
    """

    def update(self, request, *args, **kwargs):
        return UpdateModelMixin.update(self, request, *args, **kwargs)

    def perform_update(self, serializer):
        return UpdateModelMixin.perform_update(self, serializer)


class CompanyAccessMixin:
    """
    Filter queryset to only allow users to see their own company data.
    """
    permission_classes = (IsAuthenticated,)

    def get_queryset(self):
        if not self.model:
            raise NotImplementedError(
                "Viewsets with `CompanyAccessMixin` must define a `model` property.",
            )
        return self.model.objects.filter(company=self.request.user.profile.company)


class CreatedByMixin:
    def perform_create(self, serializer):
        """
        Save the request user as the `created_by` user.
        """
        serializer.save(created_by=self.request.user)


class CSVBulkExporterMixin:
    @action(detail=False, permission_classes=[IsAuthenticated])
    def bulk_export(self, request):
        from companies.tasks import generate_download

        if 'id' not in request.query_params:
            return Response({'detail': '`id` must be provided in query param.'}, 400)
        id_list = [int(_id) for _id in request.query_params.get('id').split(',')]

        download = DownloadHistory.objects.create(
            created_by=request.user,
            company=request.user.profile.company,
            download_type=self.bulk_export_type,
            filters={'id_list': id_list},
            status=DownloadHistory.Status.SENT_TO_TASK,
            is_bulk=True,
        )

        generate_download.delay(download.uuid)

        return Response({'id': download.id})


class SortOrderModelMixin:
    """
    Shared functionality to be used for models that should allow sort order rotations.
    """
    class Meta:
        ordering = ('sort_order',)

    @transaction.atomic
    def save(self, *args, **kwargs):
        model = type(self)
        if not self.sort_order:
            self.sort_order = self.max_sort_order + 1

        if self.pk:
            instance = model.objects.get(pk=self.pk)
            if instance.sort_order != self.sort_order and not kwargs.pop('in_rotate', False):
                self.rotate_sort_order(instance.sort_order, self.sort_order)

        return super().save(*args, **kwargs)

    @transaction.atomic
    def delete(self, *args, **kwargs):
        """
        Move the record that is being removed to the very bottom, rotating every other record up.
        """
        self.rotate_sort_order(self.sort_order, self.max_sort_order)
        super().delete(*args, **kwargs)

    def get_sortable_queryset(self):
        """
        Returns the base queryset to use for interacting with the model's sort order objects.
        """
        raise NotImplementedError(
                f'`{self._meta.model_name}` has not created the `get_sortable_queryset`')

    @property
    def max_sort_order(self):
        """
        Returns the last item's sort order.
        """
        base_queryset = self.get_sortable_queryset()
        return 0 if not base_queryset else base_queryset.latest('sort_order').sort_order

    def rotate_sort_order(self, old_sort_order, new_sort_order):
        """
        The beginning and end of the sort order.

        :param old_sort_order int: The original sort order the record had.
        :param new_sort_order int: The new sort order to switch this record to.
        """
        base_queryset = self.get_sortable_queryset()

        if new_sort_order < old_sort_order:
            queryset = base_queryset.filter(
                sort_order__gte=new_sort_order,
                sort_order__lt=old_sort_order,
            )
            direction = 1
        else:
            queryset = base_queryset.filter(
                sort_order__gt=old_sort_order,
                sort_order__lte=new_sort_order,
            )
            direction = -1

        # We set an `in_rotate` flag to prevent this record from calling this method multiple times.
        for instance in queryset:
            instance.sort_order = F('sort_order') + direction
            instance.save(update_fields=['sort_order'], in_rotate=True)
