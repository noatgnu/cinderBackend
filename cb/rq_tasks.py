import csv
import json
import os
import shutil
import uuid

import pandas as pd
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer, channel_layers
from django.conf import settings
from django.core.signing import TimestampSigner
from django.db.models import Q
from django_rq import job
from rq.job import Job
import re

from cb.models import SearchSession, AnalysisGroup, CurtainData, Abs, SearchResult, SourceFile, MetadataColumn, Species, \
    MSUniqueVocabularies, Unimod


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

@job('default', timeout='3h')
def export_sdrf_task(analysis_group_id: int, uuid_str: str, session_id: str):
    tempt_path = os.path.join(settings.MEDIA_ROOT, "temp", uuid_str+".sdrf.tsv")
    analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)
    source_files = SourceFile.objects.filter(analysis_group=analysis_group)
    columns = MetadataColumn.objects.filter(analysis_group=analysis_group, source_file__in=source_files)
    unique_column_position_sorted = columns.values('column_position').distinct().order_by('column_position')
    source_file_column_position_column_map = {}
    column_header_map = {}
    for c in columns:
        if c.source_file.id not in source_file_column_position_column_map:
            source_file_column_position_column_map[c.source_file.id] = {}
        if c.column_position not in column_header_map:
            if c.name == "Tissue":
                column_header_map[c.column_position] = f"{c.type}[organism part]".lower()
            elif c.type == "" or not c.type:
                column_header_map[c.column_position] = f"{c.name}".lower()
            else:
                column_header_map[c.column_position] = f"{c.type}[{c.name}]".lower()
        source_file_column_position_column_map[c.source_file.id][c.column_position] = c
    sdrf = []

    for s in source_files:
        row = [s.name]
        for c in unique_column_position_sorted:
            if c["column_position"] in source_file_column_position_column_map[s.id]:
                column = source_file_column_position_column_map[s.id][c["column_position"]]
                if column.not_applicable:
                    row.append("not applicable")
                else:
                    if column.value:
                        name = column.name.lower()
                        if name == "organism":
                            species = Species.objects.filter(official_name=column.value)
                            if species.exists():
                                row.append(f"http://purl.obolibrary.org/obo/NCBITaxon_{species.first().taxon}")
                            else:
                                row.append(column.value)
                        elif name == "label":
                            vocab = MSUniqueVocabularies.objects.filter(name=column.value, term_type="sample attribute")
                            if vocab.exists():
                                row.append(f"AC={vocab.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "cleavage agent details":
                            vocab = MSUniqueVocabularies.objects.filter(name=column.value, term_type="cleavage agent")
                            if vocab.exists():
                                row.append(f"AC={vocab.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "instrument":
                            vocab = MSUniqueVocabularies.objects.filter(name=column.value, term_type="instrument")
                            if vocab.exists():
                                row.append(f"AC={vocab.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "modification parameters":
                            splitted = column.value.split(";")
                            unimod = Unimod.objects.filter(name=splitted[0])
                            if unimod.exists():
                                row.append(f"AC={unimod.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "dissociation method":
                            dissociation = MSUniqueVocabularies.objects.filter(name=column.value, term_type="dissociation method")
                            if dissociation.exists():
                                row.append(f"AC={dissociation.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                    else:
                        row.append("not available")
            else:
                row.append("not applicable")
        sdrf.append(row)

    sdrf.insert(0, [f"source name"] + [column_header_map[i['column_position']] for i in unique_column_position_sorted])

    with open(tempt_path, 'w', newline='') as csvfile:
        writer = csv.writer(csvfile, delimiter='\t')
        writer.writerows(sdrf)

    signer = TimestampSigner()
    value = signer.sign(f"{uuid_str}.sdrf.tsv")
    channel_layer = get_channel_layer()
    async_to_sync(channel_layer.group_send)(
        f"curtain_{session_id}", {
            "type": "curtain_message", "message": {
                "type": "export_sdrf_status",
                "status": "complete",
                "file": value,
                "analysis_group_id": analysis_group_id,
                "job_id": uuid_str
            }})
    return tempt_path
