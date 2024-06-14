from django.urls import re_path

from cinderBackend.consumers import SearchConsumer

websocket_urlpatterns = [
    re_path(r'ws/search/(?P<session_id>[\w\-]+)/$', SearchConsumer.as_asgi()),
]