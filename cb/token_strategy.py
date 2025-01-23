from typing import Optional

from allauth.headless.tokens.base import AbstractTokenStrategy
from django.contrib.auth.models import User
from django.http import HttpRequest
from rest_framework_simplejwt.tokens import RefreshToken


class TokenStrategy(AbstractTokenStrategy):
    def create_access_token(self, request: HttpRequest) -> Optional[str]:
        return None

    def create_access_token_payload(self, request: HttpRequest) -> Optional[dict]:
        at = self.create_access_token(request)
        if not at:
            return None
        return {"access_token": at}

    def create_session_token(self, request: HttpRequest) -> Optional[str]:
        user = request.user
        if user.is_authenticated:
            refresh = RefreshToken.for_user(user)
            return str(refresh)
        return None

    def lookup_session(self, token: str) -> Optional[User]:
        try:
            refresh = RefreshToken(token)
            user_id = refresh["user_id"]
            return User.objects.get(id=user_id)
        except Exception:
            return None