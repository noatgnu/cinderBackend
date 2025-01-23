from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter


class NoNewUserSignupAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False

class HeadlessUserAdapter(DefaultAccountAdapter):
    def serialize_user(self, user):
        return {
            'id': user.id,
            'username': user.username,
            'email': user.email,
            'first_name': user.first_name,
            'last_name': user.last_name,
            'is_staff': user.is_staff,
            'is_active': user.is_active,
            'date_joined': user.date_joined,
            'last_login': user.last_login,
        }

class CustomAccountAdapter(DefaultAccountAdapter):
    def is_open_for_signup(self, request):
        return False
    def save_user(self, request, user, form, commit=True):
        user = super().save_user(request, user, form, commit=False)
        user.save()
        return user

class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    def pre_social_login(self, request, sociallogin):
        if not sociallogin.is_existing:
            user = sociallogin.user
            if not user.username:
                user.username = user.email
            user.save()