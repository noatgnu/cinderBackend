import csv
import json
import os
import shutil
import uuid

import pandas as pd
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings
from django.core.signing import TimestampSigner
from django.db.models import Q
from django_rq import job
from rq.job import Job
import re

from cb.models import SearchSession, AnalysisGroup, CurtainData, Abs, SearchResult


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
        data.get_curtain_data(session_id)
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
        project_files = analysis_group.project_files.filter(file_category__in=["searched", "df"])
        project_files.delete()
        curtain = analysis_group.curtain_data.all()
        if curtain:
            curtain.delete()
        data = CurtainData.objects.create(
            analysis_group=analysis_group,
            host=settings.CURTAIN_HOST,
            link_id=match.group(0)
        )
        async_to_sync(channel_layer.group_send)(
            f"curtain_{session_id}", {
                "type": "curtain_message", "message": {
                    "type": "curtain_compose_status",
                    "status": "started",
                    "analysis_group_id": analysis_group.id
                }})
        data.compose_analysis_group_from_curtain_data(analysis_group, session_id)
        analysis_group.save()
    async_to_sync(channel_layer.group_send)(
        f"curtain_{session_id}", {
            "type": "curtain_message", "message": {
                "type": "curtain_compose_status",
                "status": "complete",
                "analysis_group_id": analysis_group.id
            }})

@job('default', timeout='3h')
def export_search_data(search_session_id: int, filter_term: str, filter_log2_fc: float = 0, filter_log10_p: float = 0, session_id: str = None, instance_id: str = None):
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"search_{session_id}", {
            "type": "search_message", "message": {
                "type": "export_status",
                "status": "started",
                "id": search_session_id,
                "instance_id": instance_id
            }})

    filter_term = filter_term.lower()
    search_session = SearchSession.objects.get(id=search_session_id)
    result = SearchResult.objects.filter(session=search_session)
    query = Q()
    if filter_term != "":
        query &= Q(Q(search_term__icontains=filter_term) | Q(primary_id__icontains=filter_term) | Q(
            gene_name__icontains=filter_term) | Q(uniprot_id__icontains=filter_term))

    if filter_log2_fc > 0:
        result = result.annotate(abs_log2_fc=Abs('log2_fc'))
        query &= Q(abs_log2_fc__gte=filter_log2_fc)
    if filter_log10_p > 0:
        query &= Q(log10_p__lte=filter_log10_p)

    result = result.filter(query)
    if result.count() == 0:
        async_to_sync(channel_layer.group_send)(
            f"search_{session_id}", {
                "type": "search_message", "message": {
                    "type": "export_status",
                    "status": "empty",
                    "id": search_session_id,
                    "instance_id": instance_id
                }})
        return
    uuid_str = str(uuid.uuid4())
    tempt_path = os.path.join(settings.MEDIA_ROOT, "temp", uuid_str)
    if not os.path.exists(tempt_path):
        os.makedirs(tempt_path)
    with open(os.path.join(tempt_path, "searched_data.tsv"), "w") as f, open(os.path.join(tempt_path, "result_data.tsv"), "w") as f2:
        dict_writer = csv.DictWriter(f2, fieldnames=["primary_id", "gene_name", "uniprot_id", "log2_fc", "log10_p", "comparison_label", "condition_A", "condition_B", "copy_number", "rank", "analysis_group"], delimiter="\t")
        dict_searched_writer = csv.DictWriter(f, fieldnames=["primary_id", "gene_name", "uniprot_id", "Sample", "Condition", "Value", "analysis_group"], delimiter="\t")
        dict_writer.writeheader()
        dict_searched_writer.writeheader()
        for r in result:
            searched_data = json.loads(r.searched_data)
            for s in searched_data:
                dict_searched_writer.writerow({"primary_id": r.primary_id, "gene_name": r.gene_name, "uniprot_id": r.uniprot_id, "Sample": s["Sample"], "Condition": s["Condition"], "Value": s["Value"], "analysis_group": r.analysis_group.name})
            dict_writer.writerow({"primary_id": r.primary_id, "gene_name": r.gene_name, "uniprot_id": r.uniprot_id, "log2_fc": r.log2_fc, "log10_p": r.log10_p, "comparison_label": r.comparison_label, "condition_A": r.condition_A, "condition_B": r.condition_B, "copy_number": r.copy_number, "rank": r.rank, "analysis_group": r.analysis_group.name})
    shutil.make_archive(tempt_path, 'zip', tempt_path)
    shutil.rmtree(tempt_path)
    signer = TimestampSigner()
    value = signer.sign(f"{uuid_str}.zip")
    async_to_sync(channel_layer.group_send)(
        f"search_{session_id}", {
            "type": "search_message", "message": {
                "type": "export_status",
                "status": "complete",
                "id": search_session_id,
                "file": value,
                "instance_id": instance_id
            }})
    return tempt_path + ".zip"

