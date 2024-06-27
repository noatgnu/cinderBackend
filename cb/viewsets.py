import csv
import json
import os
import re
import uuid

import pandas as pd
from django.contrib.postgres.search import SearchQuery, SearchHeadline
from django.core.signing import TimestampSigner
from django.db.models import Q
from django.http import HttpResponse
from django_filters import filters
from django_filters.rest_framework import DjangoFilterBackend
from django_filters.views import FilterMixin
from drf_chunked_upload.models import ChunkedUpload
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
    SearchSession, Species, CurtainData, Abs
from cb.serializers import ProjectSerializer, AnalysisGroupSerializer, ProjectFileSerializer, \
    ComparisonMatrixSerializer, SampleAnnotationSerializer, SearchResultSerializer, SearchSessionSerializer, \
    SpeciesSerializer, CurtainDataSerializer


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
        query = Q()
        if species:
            query &= Q(species__id__in=species.split(","))


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
        count = Project.objects.count()
        return Response({"count": count}, status=status.HTTP_200_OK)

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
        if project:
            query &= Q(project__id=project)
        analysis_group_type = self.request.query_params.get('analysis_group_type', None)
        if analysis_group_type:
            query &= Q(analysis_group_type__in=analysis_group_type.split(","))
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
        return Response(list(labels), status=status.HTTP_200_OK)



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
        else:
            search_session = SearchSession.objects.create(search_term=search_term)
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
    search_fields = ['common_name', 'synonym', 'official_name', 'code']

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



