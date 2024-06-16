from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django_rq import job
from rq.job import Job

from cb.models import SearchSession


@job('default', timeout='3h')
def start_search_session(search_session_id: int):
    channel_layer = get_channel_layer()

    session = SearchSession.objects.get(id=search_session_id)
    async_to_sync(channel_layer.group_send)(
        f"search_{session.session_id}", {
            "type": "search_message", "message": {
                "type": "search_status",
                "status": "started",
                "id": session.session_id
            }})
    try:
        session.search_data()
    except Exception as e:
        print(e)
        session.failed = True
        session.save()
        async_to_sync(channel_layer.group_send)(
            f"search_{session.session_id}", {
                "type": "search_message", "message": {
                    "type": "search_status",
                    "status": "error",
                    "id": session.id,
                    "error": str(e)
                }})

        return
    if session.session_id:

        async_to_sync(channel_layer.group_send)(
            f"search_{session.session_id}", {
                "type": "search_message", "message": {
                    "type": "search_status",
                    "status": "complete",
                    "id": session.id
                }}
        )
    return session.id
