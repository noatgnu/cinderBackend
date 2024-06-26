from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django_rq import job
from rq.job import Job
import re

from cb.models import SearchSession, AnalysisGroup, CurtainData


@job('default', timeout='3h')
def start_search_session(search_session_id: int):
    channel_layer = get_channel_layer()

    session = SearchSession.objects.get(id=search_session_id)
    async_to_sync(channel_layer.group_send)(
        f"search_{session.session_id}", {
            "type": "search_message", "message": {
                "type": "search_status",
                "status": "started",
                "id": session.id
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

@job('default', timeout='3h')
def load_curtain_data(analysis_group_id: int, curtain_link: str, session_id: str):
    channel_layer = get_channel_layer()
    analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)
    pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
    match = re.search(pattern, curtain_link, re.I)
    if match:
        analysis_group.curtain_link = curtain_link
        analysis_group.curtain_data.all().delete()
        data = CurtainData.objects.create(analysis_group=analysis_group, host=settings.CURTAIN_HOST,
                                          link_id=match.group(0))
        async_to_sync(channel_layer.group_send)(
            f"curtain_{session_id}", {
                "type": "curtain_message", "message": {
                    "type": "curtain_status",
                    "status": "started",
                    "analysis_group_id": analysis_group.id
                }})
        data.get_curtain_data()
        analysis_group.save()
    async_to_sync(channel_layer.group_send)(
        f"curtain_{session_id}", {
            "type": "curtain_message", "message": {
                "type": "curtain_status",
                "status": "complete",
                "analysis_group_id": analysis_group.id
            }})

@job('default', timeout='3h')
def compose_analysis_group_from_curtain_data(analysis_group_id: int, curtain_link: str, session_id: str):
    channel_layer = get_channel_layer()
    analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)
    pattern = r'[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}'
    match = re.search(pattern, curtain_link, re.I)
    if match:
        analysis_group.curtain_link = curtain_link
        analysis_group.curtain_data.all().delete()
        project_files = analysis_group.project.project_files.filter(file_category__in=["searched", "df"])
        project_files.delete()
        data = CurtainData.objects.create(analysis_group=analysis_group, host=settings.CURTAIN_HOST,
                                          link_id=match.group(0))
        async_to_sync(channel_layer.group_send)(
            f"curtain_{session_id}", {
                "type": "curtain_message", "message": {
                    "type": "curtain_status",
                    "status": "started",
                    "analysis_group_id": analysis_group.id
                }})
        data.compose_analysis_group_from_curtain_data(analysis_group)
        analysis_group.save()
    async_to_sync(channel_layer.group_send)(
        f"curtain_{session_id}", {
            "type": "curtain_message", "message": {
                "type": "curtain_status",
                "status": "complete",
                "analysis_group_id": analysis_group.id
            }})