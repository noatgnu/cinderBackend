import csv
import json
import uuid
from idlelib.query import Query

import pandas as pd
from django.contrib.postgres.search import SearchQuery, SearchHeadline
from django.core.signing import TimestampSigner, SignatureExpired, BadSignature
from django.db.models import Q, Max
from django.http import HttpResponse
from django.contrib.auth.models import User
from django_filters import filters
from django_filters.rest_framework import DjangoFilterBackend
from django_filters.views import FilterMixin
from drf_chunked_upload.models import ChunkedUpload, AUTH_USER_MODEL
from rest_framework import viewsets, permissions, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.decorators import action
from rest_framework.filters import SearchFilter, OrderingFilter
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.parsers import JSONParser, MultiPartParser
from rest_framework.response import Response
from cb.rq_tasks import start_search_session, load_curtain_data, compose_analysis_group_from_curtain_data, \
    export_search_data
from django.conf import settings

from cb.models import Project, AnalysisGroup, ProjectFile, ComparisonMatrix, SampleAnnotation, SearchResult, \
    SearchSession, Species, CurtainData, Abs, Collate, CollateTag, LabGroup, SourceFile, MetadataColumn, \
    SubcellularLocation, Tissue, HumanDisease
from cb.serializers import ProjectSerializer, AnalysisGroupSerializer, ProjectFileSerializer, \
    ComparisonMatrixSerializer, SampleAnnotationSerializer, SearchResultSerializer, SearchSessionSerializer, \
    SpeciesSerializer, CurtainDataSerializer, CollateSerializers, CollateTagSerializer, UserSerializer, \
    LabGroupSerializer, SourceFileSerializer, MetadataColumnSerializer, SubcellularLocationSerializer, TissueSerializer, \
    HumanDiseaseSerializer


class ProjectViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    filterset_fields = ['name', 'user']
    search_fields = ['name']
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        species = self.request.query_params.get('species', None)
        lab_group = self.request.query_params.get('lab_group', None)
        users = self.request.query_params.get('users', None)
        query = Q()
        if species:
            query &= Q(species__id__in=species.split(","))
        if lab_group:
            query &= Q(user__lab_groups__id__in=lab_group.split(","))
        if users:
            query &= Q(user__id__in=users.split(","))
        return queryset.filter(query)

    def get_object(self):
        return super().get_object()

    def create(self, request, *args, **kwargs):
        name = request.data['name']
        description = request.data['description']
        project = Project.objects.create(name=name, description=description, user=request.user)
        data = ProjectSerializer(project).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        project = self.get_object()
        project.name = request.data['name']
        project.description = request.data['description']
        if 'species' in request.data:
            if not request.data['species']:
                project.species = None
            else:
                species = Species.objects.get(id=request.data['species'])
                project.species = species
        project.save()
        return Response(ProjectSerializer(project).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        project = self.get_object()
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def get_count(self, request):
        lab_group = request.query_params.get('lab_group', None)
        if lab_group:
            count = Project.objects.filter(user__lab_groups__id=lab_group).count()
        else:
            count = Project.objects.count()
        return Response({"count": count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_unique_conditions(self, request, pk=None):
        project = self.get_object()
        analysis_group = AnalysisGroup.objects.filter(project=project)
        conditions = []
        analysis_group_map = {}
        for i in analysis_group:
            analysis_group_map[i.id] = AnalysisGroupSerializer(i).data
            for f in i.project_files.all():
                for s in f.sample_annotations.all():
                    if s.annotations:
                        annotations = json.loads(s.annotations)
                        for a in annotations:
                            data = (a["Condition"], i.id)
                            if data not in conditions:
                                conditions.append(data)

        return Response([ {"Condition": i[0], "AnalysisGroup": analysis_group_map[i[1]]} for i in conditions], status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def permissions(self, request, pk=None):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.is_staff:
            return Response({"edit": True}, status=status.HTTP_200_OK)
        project = self.get_object()
        if project.user == request.user:
            return Response({"edit": True}, status=status.HTTP_200_OK)
        else:
            return Response({"edit": False}, status=status.HTTP_200_OK)

    # @action(detail=False, methods=['post'])
    # def search(self, request):
    #     query = SearchQuery(request.data['query'], search_type="websearch")
    #     files = ProjectFile.objects.filter(file_category__in=['searched', 'df'])
    #
    #     files = files.filter(file_contents__search_vector=query).annotate(headline=SearchHeadline('content__data', query, start_sel="<b>", stop_sel="</b>", highlight_all=True)).distinct()
    #     analysis = AnalysisGroup.objects.filter(project_files__in=files).distinct()
    #     analysis_file_map, file_results, found_line_term_map, found_lines_dict, project_results = extract_found_data(analysis, files)
    #
    #     project_found = len(project_results)
    #     json_data = {"files": [], "projects": []}
    #     if project_found > 0:
    #         grouped_data = {}
    #         for i in file_results:
    #             if i["id"] not in grouped_data:
    #                 grouped_data[i["id"]] = []
    #
    #             grouped_data[i["id"]].append(i)
    #         exported_data = []
    #         for i in grouped_data:
    #             xg = {
    #                 "id": i,
    #                 "data": grouped_data[i],
    #                 "lines": found_lines_dict[i],
    #                 "terms": found_line_term_map[i],
    #                 "line_term_map": found_line_term_map[i],
    #             }
    #             if i in analysis_file_map:
    #                 xg["analysis"] = analysis_file_map[i]
    #             exported_data.append(xg)
    #         exported_project = [{"id": i["id"], "data": i} for i in project_results]
    #         json_data = {
    #             "files": exported_data,
    #             "projects": exported_project
    #         }
    #     return Response(json_data, status=status.HTTP_200_OK)


class AnalysisGroupViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = AnalysisGroupSerializer
    queryset = AnalysisGroup.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    filterset_fields = ['name']
    pagination_class = LimitOffsetPagination
    search_fields = ['name']

    def get_queryset(self):
        queryset = super().get_queryset()
        query = Q()
        project = self.request.query_params.get('project', None)
        lab_group = self.request.query_params.get('lab_group', None)
        users = self.request.query_params.get('users', None)
        if project:
            query &= Q(project__id=project)
        analysis_group_type = self.request.query_params.get('analysis_group_type', None)
        if analysis_group_type:
            query &= Q(analysis_group_type__in=analysis_group_type.split(","))
        if lab_group:
            query &= Q(project__user__lab_groups__id__in=lab_group.split(","))
        if users:
            query &= Q(project__user__id__in=users.split(","))
        return queryset.filter(query)

    def create(self, request, *args, **kwargs):
        name = request.data['name']
        description = request.data['description']
        project_id = request.data['project']

        project = Project.objects.get(id=project_id)
        analysis_group = AnalysisGroup.objects.create(name=name, description=description, project=project)
        if "analysis_group_type" in request.data:
            analysis_group.analysis_group_type = request.data['analysis_group_type']
        if "curtain_link" in request.data:
            analysis_group.curtain_link = request.data['curtain_link']

        data = AnalysisGroupSerializer(analysis_group).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        analysis_group: AnalysisGroup = self.get_object()
        analysis_group.name = request.data['name']
        analysis_group.description = request.data['description']
        if "curtain_link" in request.data:
            if analysis_group.curtain_link != request.data['curtain_link']:
                #project_files = analysis_group.project_files.all()
                #load_curtain_data.delay(analysis_group.id, request.data['curtain_link'], request.data['session_id'])
                analysis_group.curtain_link = request.data['curtain_link']
        analysis_group.save()
        return Response(AnalysisGroupSerializer(analysis_group).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def refresh_curtain_data(self, request, pk=None):
        analysis_group = self.get_object()
        session_id = self.request.data['session_id']
        project_files = analysis_group.project_files.all()
        df_files = project_files.filter(file_category='df')
        searched_files = project_files.filter(file_category='searched')
        if df_files.exists() and searched_files.exists():
            load_curtain_data.delay(analysis_group.id, analysis_group.curtain_link, session_id)
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def compose_files_from_curtain_data(self, request, pk=None):
        analysis_group = self.get_object()
        session_id = self.request.data['session_id']
        compose_analysis_group_from_curtain_data.delay(analysis_group.id, analysis_group.curtain_link, session_id)
        return Response(status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        analysis_group = self.get_object()
        analysis_group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def files(self, request, pk=None):
        analysis_group = self.get_object()
        files = ProjectFile.objects.filter(analysis_group=analysis_group)
        data = ProjectFileSerializer(files, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], permission_classes=[permissions.AllowAny])
    def get_count(self, request):
        lab_group = request.query_params.get('lab_group', None)
        if lab_group:
            count = AnalysisGroup.objects.filter(project__user__lab_groups__id=lab_group).count()
        else:
            count = AnalysisGroup.objects.count()
        return Response({"count": count}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_curtain_data(self, request, pk=None):
        analysis_group = self.get_object()
        data = CurtainData.objects.filter(analysis_group=analysis_group)
        if not data.exists():
            return Response(status=status.HTTP_404_NOT_FOUND)
        data = CurtainDataSerializer(data.first()).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def permissions(self, request, pk=None):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.is_staff:
            return Response({"edit": True}, status=status.HTTP_200_OK)
        analysis_group = self.get_object()
        if analysis_group.project.user == request.user:
            return Response({"edit": True}, status=status.HTTP_200_OK)
        else:
            return Response({"edit": False}, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def reorganize_column(self, request, pk=None):
        analysis_group = self.get_object()
        if analysis_group.project.user != request.user:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)
        objects = []
        id_positions_list = request.data['positions']
        columns_in_analysis_group = MetadataColumn.objects.filter(analysis_group=analysis_group)
        for i in id_positions_list:
            column = columns_in_analysis_group.get(id=i['id'])
            column.column_position = i['column_position']
            objects.append(column)
        MetadataColumn.objects.bulk_update(objects, ['column_position'])
        return Response(status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def export_sdrf(self, request, pk=None):
        analysis_group = self.get_object()
        source_files = SourceFile.objects.filter(analysis_group=analysis_group)
        columns = MetadataColumn.objects.filter(analysis_group=analysis_group, source_file__in=source_files)
        unique_column_position_sorted = columns.values('column_position').distinct().order_by('column_position')
        source_file_column_position_column_map = {}
        column_header_map = {}
        for c in columns:
            if c.source_file.id not in source_file_column_position_column_map:
                source_file_column_position_column_map[c.source_file.id] = {}
            if c.column_position not in column_header_map:
                column_header_map[c.column_position] = f"{c.type}[{c.name}]".lower()
            source_file_column_position_column_map[c.source_file.id][c.column_position] = c
        sdrf = []

        for s in source_files:
            row = [s.name]
            for c in unique_column_position_sorted:
                if c['column_position'] in source_file_column_position_column_map[s.id]:
                    column = source_file_column_position_column_map[s.id][c['column_position']]
                    row.append(column.column_name)
                else:
                    row.append("")
            sdrf.append(row)

        sdrf.insert(0, [f"sample name"] + [column_header_map[i['column_position']] for i in unique_column_position_sorted])
        return Response(sdrf, status=status.HTTP_200_OK)



class ProjectFileViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = ProjectFileSerializer
    queryset = ProjectFile.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset

    def create(self, request, *args, **kwargs):
        name = request.data['name']
        description = request.data['description']
        file_type = request.data['file_type']
        file_category = request.data['file_category']
        project_id = request.data['project']
        project = Project.objects.get(id=project_id)
        project_file = ProjectFile.objects.create(name=name, description=description, file_type=file_type, file_category=file_category, project=project)
        data = ProjectFileSerializer(project_file).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        project_file = self.get_object()
        if 'name' in request.data:
            project_file.name = request.data['name']
        if 'description' in request.data:
            project_file.description = request.data['description']
        if 'file_type' in request.data:
            project_file.file_type = request.data['file_type']
        if 'file_category' in request.data:
            project_file.file_category = request.data['file_category']
        if 'extra_data' in request.data:
            project_file.extra_data = json.dumps(request.data['extra_data'])

        project_file.save()
        return Response(ProjectFileSerializer(project_file).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        project_file = self.get_object()
        project_file.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'])
    def bind_uploaded_file(self, request):
        analysis_group_id = request.data['analysis_group']
        analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)

        upload_id = request.data['upload_id']
        file_name = request.data['file_name']
        file_type = request.data['file_type']
        file_category = request.data['file_category']
        exist_file = analysis_group.project_files.all().filter(file_category=file_category)
        if exist_file.exists():
            exist_file.delete()

        upload = ChunkedUpload.objects.get(id=upload_id)
        project_file = ProjectFile()
        project_file.name = file_name
        project_file.file_type = file_type
        project_file.file_category = file_category
        project_file.analysis_group = analysis_group
        with open(upload.file.path, 'rb') as f:
            project_file.file.save(upload.filename, f)
        project_file.load_file_content = True
        project_file.save_altered()
        upload.delete()
        return Response(ProjectFileSerializer(project_file).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['get'])
    def get_columns(self, request, pk=None):
        project_file = self.get_object()
        with project_file.file.open("rt") as f:
            line = f.readline()
            delimiter = project_file.get_delimiter()
            headers = next(csv.reader([line.rstrip()], delimiter=delimiter, quotechar='"'))
            return Response(headers, status=status.HTTP_200_OK)


    @action(detail=True, methods=['get'])
    def sample_annotations(self, request, pk=None):
        file = self.get_object()
        sample_annotations = SampleAnnotation.objects.filter(file=file)
        data = SampleAnnotationSerializer(sample_annotations.first(), many=False).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def comparison_matrices(self, request, pk=None):
        file = self.get_object()
        comparison_matrices = ComparisonMatrix.objects.filter(file=file)
        data = ComparisonMatrixSerializer(comparison_matrices.first(), many=False).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def get_unique_comparison_label(self, request, pk=None):
        file = self.get_object()
        column = request.query_params.get('column', None)
        if not column:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        with file.file.open("rt") as f:
            data = pd.read_csv(f, sep=None)
            labels = data[column].unique()
            labels = labels[~pd.isnull(labels)]
        return Response(list(labels), status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def request_download_token(self, request, pk=None):
        file = self.get_object()
        signer = TimestampSigner()
        token = signer.sign(file.id)
        return Response({"token":token}, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def download(self, request):
        token = request.query_params.get('token', None)
        signer = TimestampSigner()
        try:
            file_id = signer.unsign(token, max_age=60*30)
            file = ProjectFile.objects.get(id=file_id)
            file_path = file.file.path.replace(str(settings.MEDIA_ROOT), "/media")
            response = HttpResponse(status=200)
            response["Content-Disposition"] = f'attachment; filename="{file.name}"'
            response["X-Accel-Redirect"] = f"{file_path}"
            return response
        except Exception as e:
            return Response(status=status.HTTP_400_BAD_REQUEST)



class ComparisonMatrixViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = ComparisonMatrixSerializer
    queryset = ComparisonMatrix.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        name = request.data['name']
        matrix = request.data['matrix']
        analysis_group_id = request.data['analysis_group']
        file = request.data['file']
        analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)
        project_file = ProjectFile.objects.get(id=file)
        comparison_matrix = ComparisonMatrix.objects.create(name=name, matrix=json.dumps(matrix), analysis_group=analysis_group, file=project_file)
        data = ComparisonMatrixSerializer(comparison_matrix).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        comparison_matrix = self.get_object()
        if 'matrix' in request.data:
            comparison_matrix.matrix = json.dumps(request.data['matrix'])
        if 'name' in request.data:
            comparison_matrix.name = request.data['name']
        comparison_matrix.save()
        return Response(ComparisonMatrixSerializer(comparison_matrix).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        comparison_matrix = self.get_object()
        comparison_matrix.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SampleAnnotationViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = SampleAnnotationSerializer
    queryset = SampleAnnotation.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        name = request.data['name']
        annotations = request.data['annotations']
        analysis_group_id = request.data['analysis_group']
        file = request.data['file']
        analysis_group = AnalysisGroup.objects.get(id=analysis_group_id)
        project_file = ProjectFile.objects.get(id=file)
        sample_annotation = SampleAnnotation.objects.create(name=name, annotations=json.dumps(annotations), analysis_group=analysis_group, file=project_file)
        data = SampleAnnotationSerializer(sample_annotation).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        sample_annotation = self.get_object()
        if 'annotations' in request.data:
            sample_annotation.annotations = json.dumps(request.data['annotations'])
        if 'name' in request.data:
            sample_annotation.name = request.data['name']
        sample_annotation.save()
        return Response(SampleAnnotationSerializer(sample_annotation).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        sample_annotation = self.get_object()
        sample_annotation.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)




class SearchResultViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = SearchResultSerializer
    queryset = SearchResult.objects.all()
    permission_classes = [permissions.AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'created_at', 'log2_fc', 'log10_p', 'search_term']
    search_fields = ['search_term', 'gene_name', 'uniprot_id', 'primary_id']

    def get_queryset(self):
        query = Q()
        search_id = self.request.query_params.get('search_id', None)
        if search_id:
            query &= Q(session_id=search_id)
        file_category = self.request.query_params.get('file_category', None)
        if file_category:
            query &= Q(file__file_category=file_category)
        primary_id = self.request.query_params.get('primary_id', None)
        if primary_id:
            query &= Q(primary_id=primary_id)
        log2_fc = self.request.query_params.get('log2_fc', None)
        if log2_fc:
            self.queryset = self.queryset.annotate(abs_log2_fc=Abs('log2_fc'))
            query &= Q(abs_log2_fc__gte=float(log2_fc))
        log10_p = self.request.query_params.get('log10_p', None)
        if log10_p:
            query &= Q(log10_p__gte=float(log10_p))
        result = self.queryset.filter(query)
        return result.all()

    def get_object(self):
        object = super().get_object()
        print(object)
        return object

    def create(self, request, *args, **kwargs):
        return Response(status=status.HTTP_405_METHOD_NOT_ALLOWED)

    def update(self, request, *args, **kwargs):
        search_result = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if 'search_results' in request.data:
            search_result.search_results = json.dumps(request.data['search_results'])
        if 'search_term' in request.data:
            search_result.search_term = request.data['search_term']
        if 'search_count' in request.data:
            search_result.search_count = request.data['search_count']
        search_result.save()
        return Response(SearchResultSerializer(search_result).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        search_result = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        search_result.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['get'])
    def get_related(self, request, pk=None):
        search_result = self.get_object()
        result_from_same_session_and_analysis_group = SearchResult.objects.filter(session=search_result.session, analysis_group=search_result.analysis_group, primary_id=search_result.primary_id).exclude(id=search_result.id)
        data = SearchResultSerializer(result_from_same_session_and_analysis_group, many=True).data
        return Response(data, status=status.HTTP_200_OK)


class SearchSessionViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = SearchSessionSerializer
    queryset = SearchSession.objects.all()
    permission_classes = [permissions.AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'created_at']
    filterset_fields = ['search_term']

    def get_queryset(self):
        query =Q()
        session_id = self.request.query_params.get('session_id', None)
        if session_id:
            query &= Q(session_id=session_id)
        user_owned_only = self.request.query_params.get('user_owned_only', 'false')
        if user_owned_only == 'true':
            query &= Q(user=self.request.user)


        return self.queryset.filter(query)

    def get_object(self):
        return super().get_object()

    def create(self, request, *args, **kwargs):
        search_term = request.data['search_term']
        fc_cutoff = request.data['fc_cutoff']
        p_value_cutoff = request.data['p_value_cutoff']
        search_mode = request.data['search_mode']
        analysis_groups = request.data['analysis_groups']
        user = self.request.user
        if 'session_id' in request.data:
            session_id = request.data['session_id']
            search_session = SearchSession.objects.create(search_term=search_term, session_id=session_id)
            search_sessions = SearchSession.objects.filter(session_id=session_id).order_by('-created_at')
            if search_sessions.count() > 50:
                for session in search_sessions[50:]:
                    session.delete()
        else:
            search_session = SearchSession.objects.create(search_term=search_term)
        if 'species' in request.data:
            species = Species.objects.get(id=request.data['species'])
            search_session.species = species
        search_session.log2_fc = float(fc_cutoff)
        search_session.log10_p_value = float(p_value_cutoff)
        search_session.search_mode = search_mode
        # check if user is not anonymous
        if user.is_authenticated:
            search_session.user = user
        search_session.save()
        analysis_groups = AnalysisGroup.objects.filter(id__in=analysis_groups)

        search_session.analysis_groups.set(analysis_groups)
        start_search_session.delay(search_session.id)
        data = SearchSessionSerializer(search_session).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        search_session = self.get_object()
        if 'search_term' in request.data:
            search_session.search_term = request.data['search_term']
        if 'analysis_groups' in request.data:
            analysis_groups = AnalysisGroup.objects.filter(id__in=request.data['analysis_groups'])
            search_session.analysis_groups.set(analysis_groups)
        search_session.save()
        return Response(SearchSessionSerializer(search_session).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        search_session = self.get_object()
        if not self.request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if search_session.user != self.request.user:
            return Response(status=status.HTTP_403_FORBIDDEN)
        search_session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post'])
    def get_analysis_groups_from_projects(self, request):
        project_ids = request.data['projects']
        analysis_groups = AnalysisGroup.objects.filter(project__id__in=project_ids)
        data = AnalysisGroupSerializer(analysis_groups, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def session_id(self, request):
        return Response(str(uuid.uuid4()), status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def export_search_data(self, request, pk=None):
        sample_annotation = self.get_object()
        filter_term = request.data['search_term']
        filter_log2_fc = request.data.get('log2_fc', 0)
        filter_log10_p = request.data.get('log10_p', 0)
        session_id = request.data['session_id']
        instance_id = request.data.get('instance_id', None)
        export_search_data.delay(sample_annotation.id, filter_term, filter_log2_fc, filter_log10_p, session_id, instance_id)
        return Response(status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def download_temp_file(self, request):
        token = request.query_params.get('token', None)
        print(token)
        if not token:
            return Response(status=status.HTTP_400_BAD_REQUEST)
        signer = TimestampSigner()
        try:
            data = signer.unsign(token, max_age=60*30)
            response = HttpResponse(status=200)
            response["Content-Disposition"] = f'attachment; filename="{data}"'
            response["X-Accel-Redirect"] = f"/media/temp/{data}"
            return response
        except Exception as e:
            return Response(status=status.HTTP_400_BAD_REQUEST)

class SpeciesViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = SpeciesSerializer
    queryset = Species.objects.all()
    permission_classes = [permissions.AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'taxon', 'official_name', 'code', 'common_name', 'synonym']
    filterset_fields = ['taxon', 'official_name', 'code', 'common_name', 'synonym']
    search_fields = ['^common_name', '^official_name']

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        name = request.data['name']
        species = Species.objects.create(name=name)
        data = SpeciesSerializer(species).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        species = self.get_object()
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if 'name' in request.data:
            species.name = request.data['name']
        species.save()
        return Response(SpeciesSerializer(species).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        species = self.get_object()
        species.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SubcellularLocationViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = SubcellularLocationSerializer
    queryset = SubcellularLocation.objects.all()
    permission_classes = [permissions.AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['location_identifier', 'synonyms']
    search_fields = ['^location_identifier', '^synonyms']

    def get_queryset(self):
        return super().get_queryset()


class TissueViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = TissueSerializer
    queryset = Tissue.objects.all()
    permission_classes = [permissions.AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['identifier', 'synonyms']
    search_fields = ['^identifier', '^synonyms']

    def get_queryset(self):
        return super().get_queryset()


class HumanDiseaseViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = HumanDiseaseSerializer
    queryset = HumanDisease.objects.all()
    permission_classes = [permissions.AllowAny]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['identifier', 'synonyms']
    search_fields = ['^identifier', '^synonyms', '^acronym']

    def get_queryset(self):
        return super().get_queryset()

class CollateViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = CollateSerializers
    queryset = Collate.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'title', 'created_at']
    filterset_fields = ['title']
    search_fields = ['title']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        tag_ids = self.request.query_params.get('tag_ids', None)
        lab_group = self.request.query_params.get('lab_group', None)
        users = self.request.query_params.get('users', None)
        query = Q()
        if tag_ids:
            tags = CollateTag.objects.filter(id__in=tag_ids.split(","))
            query &= Q(tags__in=tags)

        if lab_group:
            query &= Q(users__lab_groups__id__in=lab_group.split(","))

        if users:
            query &= Q(users__id__in=users.split(","))


        return self.queryset.filter(query).distinct()

    def create(self, request, *args, **kwargs):
        user = request.user
        collate = Collate.objects.create(
            title=request.data['title'],
            greeting=request.data['greeting'],
        )
        collate.users.add(user)
        collate.save()
        data = CollateSerializers(collate).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        collate = self.get_object()
        collate.title = request.data['title']
        collate.greeting = request.data['greeting']
        if 'settings' in request.data:
            collate.settings = request.data['settings']
        if 'projects' in request.data:
            project_ids = [i["id"] for i in request.data['projects']]
            projects = Project.objects.filter(id__in=project_ids)
            # remove all projects
            collate.projects.clear()
            # add new projects
            collate.projects.add(*projects)
        collate.save()
        return Response(CollateSerializers(collate).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        collate = self.get_object()
        collate.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def add_tags(self, request, pk=None):
        collate = self.get_object()
        tags = request.data['tags']
        tags = CollateTag.objects.filter(id__in=tags)
        for tag in tags:
            collate.tags.add(tag)
        collate.save()
        return Response(CollateSerializers(collate).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_tags(self, request, pk=None):
        collate = self.get_object()
        tags = request.data['tags']
        tags = CollateTag.objects.filter(id__in=tags)
        for tag in tags:
            collate.tags.remove(tag)
        collate.save()
        return Response(CollateSerializers(collate).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['get'])
    def permissions(self, request, pk=None):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        if request.user.is_staff:
            return Response({"edit": True}, status=status.HTTP_200_OK)
        collate = self.get_object()
        if request.user in collate.users.all():
            return Response({"edit": True}, status=status.HTTP_200_OK)
        else:
            return Response({"edit": False}, status=status.HTTP_200_OK)


class CollateTagViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = CollateTagSerializer
    queryset = CollateTag.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    filterset_fields = ['name']
    search_fields = ['name']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        tag = CollateTag.objects.create(
            name=request.data['name'],
        )
        data = CollateTagSerializer(tag).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        tag = self.get_object()
        tag.name = request.data['name']
        tag.save()
        return Response(CollateTagSerializer(tag).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        tag = self.get_object()
        tag.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def add_to_collate(self, request, pk=None):
        tag = self.get_object()
        collate_id = self.request.data['collate']
        collate = Collate.objects.get(id=collate_id)
        collate.tags.add(tag)
        collate.save()
        return Response(CollateTagSerializer(tag).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_from_collate(self, request, pk=None):
        tag = self.get_object()
        collate_id = self.request.data['collate']
        collate = Collate.objects.get(id=collate_id)
        collate.tags.remove(tag)
        collate.save()
        return Response(status=status.HTTP_200_OK)


class UserViewSet(FilterMixin, viewsets.ModelViewSet):
    serializer_class = UserSerializer
    queryset = User.objects.all()
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'first_name', 'last_name', 'created_at']
    filterset_fields = ['first_name', 'last_name']
    search_fields = ['first_name', 'last_name', 'username', 'email']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        query = Q()
        lab_group = self.request.query_params.get('lab_group', None)
        if lab_group:
            query &= Q(lab_groups__id__in=lab_group.split(","))
        return self.queryset.filter(query)

    def create(self, request, *args, **kwargs):
        if not request.user.is_staff:
            return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)
        User.objects.create_user(request.data['username'], request.data['email'], request.data['password'], request.data['first_name'], request.data['last_name'])
        return Response(status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        object = self.get_object()
        if request.user == object or request.user.is_staff:
            if 'email' in request.data:
                object.email = request.data['email']
            if 'password' in request.data:
                object.set_password(request.data['password'])
            if 'first_name' in request.data:
                object.first_name = request.data['first_name']
            if 'last_name' in request.data:
                object.last_name = request.data['last_name']
            if 'username' in request.data:
                if request.user.is_staff:
                    object.username = request.data['username']
            object.save()
            return Response(UserSerializer(object).data, status=status.HTTP_200_OK)
        return Response({'detail': 'Permission denied.'}, status=status.HTTP_403_FORBIDDEN)

    def destroy(self, request, *args, **kwargs):
        if request.user.is_staff:
            object = self.get_object()
            if object.is_staff:
                return Response({'detail': 'Cannot delete staff user.'}, status=status.HTTP_400_BAD_REQUEST)
            object.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)
        return Response({'detail': 'Method not allowed.'}, status=status.HTTP_405_METHOD_NOT_ALLOWED)

    @action(detail=False, methods=['get'])
    def get_current_user(self, request):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        return Response(UserSerializer(request.user).data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'])
    def get_user_lab_group(self, request):
        if not request.user.is_authenticated:
            return Response(status=status.HTTP_403_FORBIDDEN)
        user = request.user
        lab_groups = user.lab_groups.all()
        data = LabGroupSerializer(lab_groups, many=True).data
        return Response(data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], permission_classes=[permissions.AllowAny])
    def create_with_token(self, request):
        token = request.data['token']
        username = request.data['username']
        email = request.data['email']
        first_name = request.data['first_name']
        last_name = request.data['last_name']
        password = request.data['password']
        signer = TimestampSigner()
        try:
            token_data = signer.unsign(token, max_age=3600*24*7)
            if token_data == username:
                if User.objects.filter(username=username).exists():
                    return Response({'detail': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
                user = User.objects.create_user(username=username, email=email, first_name=first_name, last_name=last_name)
                user.set_password(password)
                if 'lab_group' in request.data:
                    lab_groups = LabGroup.objects.filter(id__in=request.data['lab_group'])
                    for lab_group in lab_groups:
                        lab_group.members.add(user)
                user.save()
                return Response(UserSerializer(user).data, status=status.HTTP_201_CREATED)
            else:
                return Response({"detail": "Invalid token."}, status=status.HTTP_400_BAD_REQUEST)
        except SignatureExpired:
            return Response({'detail': 'Token has expired.'},status=status.HTTP_400_BAD_REQUEST)
        except BadSignature:
            return Response({'detail': 'Invalid token.'}, status=status.HTTP_400_BAD_REQUEST)


    @action(detail=False, methods=['post'])
    def generate_token(self, request):
        if not request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        signer = TimestampSigner()
        token = signer.sign(request.data['username'])
        if User.objects.filter(username=request.data['username']).exists():
            return Response({'detail': 'Username already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        return Response({"token": token}, status=status.HTTP_200_OK)

class LabGroupViewSet(FilterMixin, viewsets.ModelViewSet):
    serializer_class = LabGroupSerializer
    queryset = LabGroup.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    filterset_fields = ['name']
    search_fields = ['name']
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        query = Q()
        name = self.request.query_params.get('name', None)
        if name:
            query &= Q(name__icontains=name)
        return queryset.filter(query)

    def create(self, request, *args, **kwargs):
        if not self.request.user.is_staff:
            return Response(status=status.HTTP_403_FORBIDDEN)
        name = request.data['name']
        lab_group = LabGroup.objects.create(name=name)
        data = LabGroupSerializer(lab_group).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        if not self.request.user.is_staff or not self.request.user in self.get_object().managing_members.all():
            return Response(status=status.HTTP_403_FORBIDDEN)
        lab_group = self.get_object()
        if 'name' in request.data:
            lab_group.name = request.data['name']
        lab_group.save()
        return Response(LabGroupSerializer(lab_group).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        lab_group = self.get_object()
        lab_group.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def add_member(self, request, pk=None):
        user_id = request.data['user']
        user = User.objects.get(id=user_id)
        if self.request.user != user:
            if not self.request.user.is_staff:
                if not self.request.user in self.get_object().managing_members.all():
                    return Response(status=status.HTTP_403_FORBIDDEN)
        lab_group = self.get_object()
        lab_group.members.add(user)
        lab_group.save()
        return Response(LabGroupSerializer(lab_group).data, status=status.HTTP_200_OK)

    @action(detail=True, methods=['post'])
    def remove_member(self, request, pk=None):
        if not self.request.user.is_staff:
            if not self.request.user in self.get_object().managing_members.all():
                return Response(status=status.HTTP_403_FORBIDDEN)

        lab_group = self.get_object()
        user_id = request.data['user']
        user = User.objects.get(id=user_id)
        lab_group.members.remove(user)
        lab_group.save()
        return Response(LabGroupSerializer(lab_group).data, status=status.HTTP_200_OK)

class SourceFileViewSet(FilterMixin, viewsets.ModelViewSet):
    serializer_class = SourceFileSerializer
    queryset = SourceFile.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    search_fields = ['name']

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        if "analysis_group" not in request.data:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        analysis_group = AnalysisGroup.objects.get(id=request.data['analysis_group'])
        if analysis_group.project.user != request.user:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)

        source_file = SourceFile(user=request.user, analysis_group=analysis_group)
        if 'name' in request.data:
            source_file.name = request.data['name']
        if 'description' in request.data:
            source_file.description = request.data['description']
        source_file.save()
        #check if there is any metadatacolumn belonging to any other sourcefile in the same analysis group. If there is, create the same number of metadatacolumn with the same name and type and position for this new sourcefile
        #get a neighboring sourcefile in the same analysis group
        neighboring_source_file = SourceFile.objects.filter(analysis_group=analysis_group).exclude(id=source_file.id).first()
        if neighboring_source_file:
            metadata_columns = MetadataColumn.objects.filter(source_file=neighboring_source_file)
            for metadata_column in metadata_columns:
                column = MetadataColumn.objects.create(analysis_group=analysis_group, source_file=source_file, name=metadata_column.name, type=metadata_column.type, column_position=metadata_column.column_position)

        data = SourceFileSerializer(source_file).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        source_file = self.get_object()
        fields = ['name', 'description']
        for i in request.data:
            if i in fields:
                setattr(source_file, i, request.data[i])
        source_file.save()

        return Response(SourceFileSerializer(source_file).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        source_file = self.get_object()
        if source_file.user != request.user and source_file.analysis_group.project.user != request.user:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)
        source_file.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MetadataColumnViewSet(FilterMixin, viewsets.ModelViewSet):
    serializer_class = MetadataColumnSerializer
    queryset = MetadataColumn.objects.all()
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    search_fields = ['name']

    def get_queryset(self):
        return super().get_queryset()

    def create(self, request, *args, **kwargs):
        if "analysis_group" not in request.data:
            return Response(status=status.HTTP_400_BAD_REQUEST)

        analysis_group = AnalysisGroup.objects.get(id=request.data['analysis_group'])
        source_file = request.data.get('source_file', None)
        if analysis_group.project.user != request.user:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)

        metadata_column_data = {
            'analysis_group': analysis_group,
            'name': request.data.get('name'),
            'type': request.data.get('type'),
            'value': request.data.get('value')
        }

        # get the last position in the metadata columns group by checking all the metadata columns of the sourcefiles in the analysis group and see the max position value
        if not source_file:
            max_column_position = \
            MetadataColumn.objects.filter(source_file__isnull=True).aggregate(Max('column_position'))[
                'column_position__max']
        else:
            max_column_position = \
            MetadataColumn.objects.filter(source_file__isnull=False).aggregate(Max('column_position'))[
                'column_position__max']
        if max_column_position is None:
            position = 0
        else:
            position = max_column_position + 1

        if not source_file:
            metadata_column_data["column_position"] = position
            metadata_column = MetadataColumn.objects.create(**metadata_column_data)
            data = MetadataColumnSerializer(metadata_column).data
            return Response([data], status=status.HTTP_201_CREATED)
        else:
            source_files = SourceFile.objects.filter(analysis_group=analysis_group)
            if source_files.exists():
                columns = []
                for s in source_files:
                    metadata_column = MetadataColumn()
                    metadata_column.source_file = s
                    metadata_column.analysis_group = analysis_group
                    metadata_column.column_position = position
                    metadata_column.name = metadata_column_data['name']
                    metadata_column.type = metadata_column_data['type']
                    if int(source_file) == s.id:
                        metadata_column.value = metadata_column_data['value']
                    columns.append(metadata_column)
                result = MetadataColumn.objects.bulk_create(columns)
                data = MetadataColumnSerializer(result, many=True).data
                return Response(data, status=status.HTTP_201_CREATED)
            else:
                return Response(status=status.HTTP_400_BAD_REQUEST)
    def update(self, request, *args, **kwargs):
        metadata_column = self.get_object()
        fields = ['name', 'description', 'value']
        for i in request.data:
            if i in fields:
                setattr(metadata_column, i, request.data[i])
        metadata_column.save()

        return Response(MetadataColumnSerializer(metadata_column).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        metadata_column = self.get_object()
        if metadata_column.analysis_group.project.user != request.user:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)
        metadata_column.value = None
        metadata_column.save()
        # check if all source_file in this analysis_group all have metadata_column.value at this column_position
        source_files = SourceFile.objects.filter(analysis_group=metadata_column.analysis_group)
        if source_files.exists():
            metadata_colums_same_position = MetadataColumn.objects.filter(analysis_group=metadata_column.analysis_group, column_position=metadata_column.column_position, source_file__in=source_files)
            if metadata_colums_same_position.exists():
                metadata_colums_same_position.delete()
            # update the column position of the metadata columns with column_position greater than the deleted column_position
            metadata_column_greater_position = MetadataColumn.objects.filter(analysis_group=metadata_column.analysis_group, column_position__gt=metadata_column.column_position, source_file__in=source_files)
            for column in metadata_column_greater_position:
                column.column_position -= 1
            MetadataColumn.objects.bulk_update(metadata_column_greater_position, ['column_position'])
            return Response(status=status.HTTP_204_NO_CONTENT)
        else:
            metadata_column.delete()
            return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=['post'])
    def empty_all_value_in_column(self, request, pk=None):
        metadata_column = self.get_object()
        if metadata_column.analysis_group.project.user != request.user:
            if not request.user.is_staff:
                return Response(status=status.HTTP_403_FORBIDDEN)

        source_files = SourceFile.objects.filter(analysis_group=metadata_column.analysis_group)
        if source_files.exists():
            metadata_colums_same_position = MetadataColumn.objects.filter(analysis_group=metadata_column.analysis_group,
                                                                          column_position=metadata_column.column_position,
                                                                          source_file__in=source_files)
            metadata_colums_same_position.update(value=None)
            data = MetadataColumnSerializer(metadata_colums_same_position, many=True).data
            return Response(data, status=status.HTTP_200_OK)
        else:
            metadata_column.value = None
            metadata_column.save()
            data = MetadataColumnSerializer(metadata_column).data
            return Response([data], status=status.HTTP_200_OK)