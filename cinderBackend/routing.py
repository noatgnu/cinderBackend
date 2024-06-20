from django.urls import re_path

from cinderBackend.consumers import SearchConsumer, CurtainConsumer

websocket_urlpatterns = [
    re_path(r'ws/search/(?P<session_id>[\w\-]+)/$', SearchConsumer.as_asgi()),
    re_path(r'ws/curtain/(?P<session_id>[\w\-]+)/$', CurtainConsumer.as_asgi()),
]