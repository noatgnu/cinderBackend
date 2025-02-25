import csv
import io
import json
import os
import shutil
import uuid

import pandas as pd
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer, channel_layers
from django.conf import settings
from django.contrib.auth.models import User
from django.core.signing import TimestampSigner
from django.db.models import Q, Max
from django_rq import job
from drf_chunked_upload.models import ChunkedUpload
from rq.job import Job
import re

from sdrf_pipelines.sdrf.sdrf import SdrfDataFrame

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
    sdrf = create_sdrf_array_from_metadata(analysis_group_id)

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


def create_sdrf_array_from_metadata(analysis_group_id):
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
        row = []
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
                                if "AC=" not in column.value:
                                    row.append(f"AC={vocab.first().accession};NT={column.value}")
                                else:
                                    row.append(f"NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "cleavage agent details":
                            vocab = MSUniqueVocabularies.objects.filter(name=column.value, term_type="cleavage agent")
                            if vocab.exists():
                                if "AC=" not in column.value:
                                    row.append(f"AC={vocab.first().accession};NT={column.value}")
                                else:
                                    row.append(f"NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "instrument":
                            vocab = MSUniqueVocabularies.objects.filter(name=column.value, term_type="instrument")
                            if vocab.exists():
                                if "AC=" not in column.value:
                                    row.append(f"AC={vocab.first().accession};NT={column.value}")
                                else:
                                    row.append(f"NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "modification parameters":
                            splitted = column.value.split(";")
                            unimod = Unimod.objects.filter(name=splitted[0])
                            if unimod.exists():
                                if "AC=" in column.value:
                                    row.append(f"NT={column.value}")
                                else:
                                    row.append(f"AC={unimod.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        elif name == "dissociation method":
                            dissociation = MSUniqueVocabularies.objects.filter(name=column.value,
                                                                               term_type="dissociation method")
                            if dissociation.exists():
                                row.append(f"AC={dissociation.first().accession};NT={column.value}")
                            else:
                                row.append(f"{column.value}")
                        else:
                            row.append(column.value)
                    else:
                        row.append("not available")
            else:
                row.append("not applicable")
        sdrf.append(row)
    sdrf.insert(0, [column_header_map[i['column_position']] for i in unique_column_position_sorted])
    return sdrf


@job('default', timeout='3h')
def validate_sdrf_file(analysis_group_id: int, session_id: str):
    sdrf = create_sdrf_array_from_metadata(analysis_group_id)
    df = SdrfDataFrame.parse(io.StringIO("\n".join(["\t".join(i) for i in sdrf])))
    errors = df.validate("default", True)
    errors = errors + df.validate("mass_spectrometry", True)
    errors = errors + df.validate_experimental_design()
    channel_layer = get_channel_layer()
    if errors:
        async_to_sync(channel_layer.group_send)(
            f"curtain_{session_id}", {
                "type": "curtain_message", "message": {
                    "type": "sdrf_validation",
                    "status": "error",
                    "analysis_group_id": analysis_group_id,
                    "errors": [str(e) for e in errors]
                }})
    else:
        async_to_sync(channel_layer.group_send)(
            f"curtain_{session_id}", {
                "type": "curtain_message", "message": {
                    "type": "sdrf_validation",
                    "status": "complete",
                    "analysis_group_id": analysis_group_id
                }})

@job('default', timeout='3h')
def process_imported_metadata_file(analysis_group_id, file_id, file_type, user_id, session_id):
    channel_layer = get_channel_layer()
    user = User.objects.get(id=user_id)
    analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)
    file = ChunkedUpload.objects.get(id=file_id)
    analysis_group.source_files.all().delete()
    sdrf_col_pattern = re.compile(r"\[(.+)\]")
    default_columns_list = [{
        "name": "Source name", "type": "", "mandatory": True
    },
        {
            "name": "Organism", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Tissue", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Disease", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Cell type", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Biological replicate", "type": "Characteristics", "mandatory": True
        }, {
            "name": "Material type", "type": "", "mandatory": True
        },
        {
            "name": "Assay name", "type": "", "mandatory": True
        }, {
            "name": "Technology type", "type": "", "mandatory": True
        }, {
            "name": "Technical replicate", "type": "Comment", "mandatory": True
        },
        {"name": "Label", "type": "Comment", "mandatory": True},
        {"name": "Fraction identifier", "type": "Comment", "mandatory": True},
        {"name": "Instrument", "type": "Comment", "mandatory": True},
        {"name": "Data file", "type": "Comment", "mandatory": True},
        {"name": "Cleavage agent details", "type": "Comment", "mandatory": True},
        {"name": "Modification parameters", "type": "Comment", "mandatory": True},
        {"name": "Dissociation method", "type": "Comment", "mandatory": True},
        {"name": "Precursor mass tolerance", "type": "Comment", "mandatory": True},
        {"name": "Fragment mass tolerance", "type": "Comment", "mandatory": True},
    ]
    default_columns = [i["name"].lower() for i in default_columns_list]
    progress_count = 0
    if file_type == "SDRF":
        df = SdrfDataFrame.parse(file.file.path)
        for ind, row in df.iterrows():
            progress_count += 1
            source_file = SourceFile()
            source_file.name = row["comment[data file]"]
            source_file.description = row["comment[data file]"]
            source_file.analysis_group = analysis_group
            source_file.user = user
            source_file.save()

            for i in df.columns:
                sdrf_col_pattern_match = sdrf_col_pattern.search(i.lower())
                metadata_column = MetadataColumn()
                if sdrf_col_pattern_match:
                    metadata_column.type = i[:sdrf_col_pattern_match.start(0)].capitalize()
                    metadata_column.name = sdrf_col_pattern_match.group(1).lower().capitalize()
                else:
                    metadata_column.name = i.lower().capitalize()
                metadata_column.column_position = df.columns.get_loc(i)
                if metadata_column.name in default_columns:
                    metadata_column.not_applicable = False
                    metadata_column.mandatory = True
                if row[i].lower() == "not applicable":
                    metadata_column.not_applicable = True
                elif row[i].lower() == "not available":
                    metadata_column.value = None
                else:
                    metadata_column.value = row[i]
                metadata_column.source_file = source_file
                metadata_column.analysis_group = analysis_group
                metadata_column.save()

            # check if the source file has all the mandatory columns and insert the default values if not in three groups, characteristics, comments and other. Missing mandatory column should be added before any non-mandatory columns. The positions of all columns should change accordingly.
            bulk_metadata_columns_characteristics = []
            bulk_metadata_columns_other = []
            bulk_metadata_columns_comments = []



            for i in default_columns_list:
                if not source_file.metadata_columns.filter(name=i["name"]).exists():
                    metadata_column = MetadataColumn()
                    metadata_column.name = i["name"]
                    metadata_column.type = i["type"]
                    metadata_column.mandatory = i["mandatory"]
                    metadata_column.source_file = source_file
                    metadata_column.analysis_group = analysis_group


            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "sdrf_import",
                        "status": "in_progress",
                        "progress": 100 / (len(df.index)) * progress_count,
                        "analysis_group_id": analysis_group_id
                    }})
    elif file_type == "Spectronaut Condition Setup File":
        df = pd.read_csv(file.file.path, sep="\t")

        for ind, row in df.iterrows():
            progress_count += 1
            source_file = SourceFile()
            source_file.name = row["File Name"]
            source_file.description = row["File Name"]
            source_file.analysis_group = analysis_group
            source_file.user = user
            source_file.save()
            source_file.initiate_default_columns()
            for m in source_file.metadata_columns.all():
                if m.name == "Assay name":
                    m.value = f"run {row['#']}"
                elif m.name == "Biological replicate":
                    m.value = row["Replicate"]
                elif m.name == "Source name":
                    m.value = f"{row['#']}"
                elif m.name == "Fraction identifier":
                    m.value = "1"
                elif m.name == "Technical replicate":
                    m.value = "1"
                elif m.name == "Data file":
                    m.value = row["Run Label"]
                m.save()
            last_characteristics_column = source_file.metadata_columns.filter(type="Characteristics").last()
            condition_metadata_column = MetadataColumn()
            condition_metadata_column.name = "Condition"
            condition_metadata_column.type = "Characteristics"
            condition_metadata_column.source_file = source_file
            condition_metadata_column.analysis_group = analysis_group
            condition_metadata_column.value = row["Condition"]
            condition_metadata_column.column_position = last_characteristics_column.column_position + 1
            # change the position of the columns after the last characteristics column
            source_file.metadata_columns.filter(column_position__gt=last_characteristics_column.column_position)
            for i in source_file.metadata_columns.filter(
                    column_position__gt=last_characteristics_column.column_position):
                i.column_position += 1
                i.save(update_fields=['column_position'])
            hightest_position = source_file.metadata_columns.aggregate(Max('column_position'))['column_position__max']
            MetadataColumn.objects.create(
                name="Condition",
                type="Factor value",
                source_file=source_file,
                analysis_group=analysis_group,
                value=row["Condition"],
                column_position=hightest_position + 1
            )
            condition_metadata_column.save()
            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "sdrf_import",
                        "status": "in_progress",
                        "progress": 100/(len(df.index))*progress_count,
                        "analysis_group_id": analysis_group_id
                    }})
    async_to_sync(channel_layer.group_send)(
        f"curtain_{session_id}", {
            "type": "curtain_message", "message": {
                "type": "sdrf_import",
                "status": "complete",
                "progress": 100,
                "analysis_group_id": analysis_group_id
            }})
