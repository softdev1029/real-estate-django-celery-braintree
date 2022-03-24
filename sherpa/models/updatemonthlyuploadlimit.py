from accounts.models.company import Company
from core import models

__all__ = (
    'UpdateMonthlyUploadLimit',
)


class UpdateMonthlyUploadLimit(models.Model):
    """
    Entered through the django admin and a task goes through to update the company's upload limit.
    Usually what happens is that a company changes plans and they need to have a change of monthly
    limit scheduled for their billing end date.
    """
    class Status:
        OPEN = 'open'
        COMPLETE = 'complete'
        ERROR = 'error'

        CHOICES = (
            (OPEN, 'Open'),
            (COMPLETE, 'Complete'),
            (ERROR, 'Error'),
        )

    company = models.ForeignKey(Company, on_delete=models.CASCADE)

    new_monthly_upload_limit = models.IntegerField(default=0)
    update_date = models.DateField()
    status = models.CharField(
        max_length=8,
        default=Status.OPEN,
        choices=Status.CHOICES,
    )

    def __str__(self):
        return "%s - %s" % (self.company.name, self.update_date)
