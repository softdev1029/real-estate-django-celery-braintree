from django.contrib.auth import get_user_model

from core import models

User = get_user_model()


class UserLogin(models.Model):
    """
    Track the time and IP of user logins.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    timestamp = models.DateTimeField(auto_now_add=True)

    # Need to allow null because the tests don't have IP Address.
    ip_address = models.CharField(max_length=128, blank=True, null=True)

    def __str__(self):
        return f"{self.user.email} - {self.timestamp}"
