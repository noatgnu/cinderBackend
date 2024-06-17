import json

from rest_framework import serializers

from cb.models import Project, ProjectFile, AnalysisGroup, SampleAnnotation, ComparisonMatrix, SearchResult, \
    SearchSession


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'hash', 'metadata', 'global_id', 'temporary', 'user', 'encrypted', 'created_at', 'updated_at']


class ProjectFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectFile
        fields = ['id', 'name', 'description', 'hash', 'file_type', 'file', 'file_category', 'project', 'load_file_content', 'created_at', 'updated_at', 'extra_data']


class AnalysisGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisGroup
        fields = ['id', 'name', 'description', 'project', 'created_at', 'updated_at', 'ptm', 'curtain_link']


class SampleAnnotationSerializer(serializers.ModelSerializer):
    class Meta:
        model = SampleAnnotation
        fields = ['id', 'name', 'analysis_group', 'annotations', 'created_at', 'updated_at', 'file']


class ComparisonMatrixSerializer(serializers.ModelSerializer):
    class Meta:
        model = ComparisonMatrix
        fields = ['id', 'name', 'analysis_group', 'matrix', 'created_at', 'updated_at', 'file']


class SearchResultSerializer(serializers.ModelSerializer):
    file = serializers.SerializerMethodField()
    analysis_group = serializers.SerializerMethodField()
    searched_data = serializers.SerializerMethodField()

    def get_file(self, search_result):
        return {'id': search_result.file.id, 'name': search_result.file.name, 'file_type': search_result.file.file_type, 'file_category': search_result.file.file_category}

    def get_analysis_group(self, search_result):
        return {'id': search_result.analysis_group.id, 'name': search_result.analysis_group.name, 'ptm': search_result.analysis_group.ptm}

    def get_searched_data(self, search_result):
        if search_result.searched_data is None:
            return None
        return json.loads(search_result.searched_data)

    class Meta:
        model = SearchResult
        fields = ['id', 'search_term', 'created_at', 'updated_at', 'session', 'analysis_group', 'file', 'primary_id', 'gene_name', 'uniprot_id',
                  'log2_fc', 'log10_p', 'searched_data', 'comparison_label', 'condition_A', 'condition_B']


class SearchSessionSerializer(serializers.ModelSerializer):
    user = serializers.SerializerMethodField()
    analysis_groups = serializers.SerializerMethodField()

    def get_analysis_groups(self, search_session):
        return [i.id for i in search_session.analysis_groups.all()]

    def get_user(self, search_session):
        if search_session.user is None:
            return None
        return search_session.user.username


    class Meta:
        model = SearchSession
        fields = ['id', 'search_term', 'created_at', 'updated_at', 'analysis_groups', 'user', 'session_id']