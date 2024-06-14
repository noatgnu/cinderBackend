import csv
import json
import os
import re
import uuid

from django.contrib.postgres.search import SearchQuery, SearchHeadline
from django.db.models import Q
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
from cb.rq_tasks import start_search_session

from cb.models import Project, AnalysisGroup, ProjectFile, ComparisonMatrix, SampleAnnotation, SearchResult, \
    SearchSession
from cb.serializers import ProjectSerializer, AnalysisGroupSerializer, ProjectFileSerializer, \
    ComparisonMatrixSerializer, SampleAnnotationSerializer, SearchResultSerializer, SearchSessionSerializer


class ProjectViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = ProjectSerializer
    queryset = Project.objects.all()
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'name', 'created_at']
    filterset_fields = ['name', 'user']
    search_fields = ['name']
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser, JSONParser)
    pagination_class = LimitOffsetPagination

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(user=self.request.user)

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
        project.save()
        return Response(ProjectSerializer(project).data, status=status.HTTP_200_OK)

    def destroy(self, request, *args, **kwargs):
        project = self.get_object()
        project.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

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
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [TokenAuthentication]
    parser_classes = (MultiPartParser,JSONParser)
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['name']
    pagination_class = LimitOffsetPagination
    search_fields = ['name']

    def get_queryset(self):
        queryset = super().get_queryset()
        if 'project' in self.request.query_params:
            project_id = self.request.query_params['project']
            return queryset.filter(project__id=project_id)
        return queryset

    def create(self, request, *args, **kwargs):
        name = request.data['name']
        description = request.data['description']
        project_id = request.data['project']
        project = Project.objects.get(id=project_id)
        analysis_group = AnalysisGroup.objects.create(name=name, description=description, project=project)
        data = AnalysisGroupSerializer(analysis_group).data
        return Response(data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        analysis_group = self.get_object()
        analysis_group.name = request.data['name']
        analysis_group.description = request.data['description']
        analysis_group.save()
        return Response(AnalysisGroupSerializer(analysis_group).data, status=status.HTTP_200_OK)

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



class ProjectFileViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = ProjectFileSerializer
    queryset = ProjectFile.objects.all()
    permission_classes = [permissions.IsAuthenticated]
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
        project_file.name = request.data['name']
        project_file.description = request.data['description']
        project_file.file_type = request.data['file_type']
        project_file.file_category = request.data['file_category']
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


class ComparisonMatrixViewSet(viewsets.ModelViewSet, FilterMixin):
    serializer_class = ComparisonMatrixSerializer
    queryset = ComparisonMatrix.objects.all()
    permission_classes = [permissions.IsAuthenticated]
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
    permission_classes = [permissions.IsAuthenticated]
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
    filter_backends  = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    ordering_fields = ['id', 'created_at']

    def get_queryset(self):
        query = Q()
        search_id = self.request.query_params.get('search_id', None)
        if search_id:
            query &= Q(session_id=search_id)
        file_category = self.request.query_params.get('file_category', None)
        if file_category:
            query &= Q(file__file_category=file_category)
        return self.queryset.filter(query)

    def get_object(self):
        return super().get_object()

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
        result_from_same_session_and_analysis_group = SearchResult.objects.filter(session=search_result.session, analysis_group=search_result.analysis_group).exclude(id=search_result.id)
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
        analysis_groups = request.data['analysis_groups']
        user = self.request.user
        if 'session_id' in request.data:
            session_id = request.data['session_id']
            search_session = SearchSession.objects.create(search_term=search_term, session_id=session_id)
        else:
            search_session = SearchSession.objects.create(search_term=search_term)
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
        search_session.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['get'])
    def session_id(self, request):
        return Response(str(uuid.uuid4()), status=status.HTTP_200_OK)


