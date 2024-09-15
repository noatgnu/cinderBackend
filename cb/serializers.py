import json

from django.conf import settings
from django.contrib.auth.models import User
from rest_framework import serializers

from cb.models import Project, ProjectFile, AnalysisGroup, SampleAnnotation, ComparisonMatrix, SearchResult, \
    SearchSession, Species, CurtainData, Collate, CollateTag, LabGroup


class ProjectSerializer(serializers.ModelSerializer):
    class Meta:
        model = Project
        fields = ['id', 'name', 'description', 'hash', 'metadata', 'global_id', 'temporary', 'user', 'encrypted', 'created_at', 'updated_at', 'species']


class ProjectFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = ProjectFile
        fields = ['id', 'name', 'description', 'hash', 'file_type', 'file', 'file_category', 'project', 'load_file_content', 'created_at', 'updated_at', 'extra_data']


class AnalysisGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalysisGroup
        fields = ['id', 'name', 'description', 'project', 'created_at', 'updated_at', 'analysis_group_type', 'curtain_link']


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
        return {'id': search_result.analysis_group.id, 'name': search_result.analysis_group.name, 'analysis_group_type': search_result.analysis_group.analysis_group_type}

    def get_searched_data(self, search_result):
        if search_result.searched_data is None:
            return None
        return json.loads(search_result.searched_data)

    class Meta:
        model = SearchResult
        fields = ['id', 'search_term', 'created_at', 'updated_at', 'session', 'analysis_group', 'file', 'primary_id', 'gene_name', 'uniprot_id',
                  'log2_fc', 'log10_p', 'searched_data', 'comparison_label', 'condition_A', 'condition_B', 'copy_number', 'rank']


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

class SpeciesSerializer(serializers.ModelSerializer):
    class Meta:
        model = Species
        fields = ['id', 'code', 'taxon', 'common_name', 'official_name', 'synonym']

class CurtainDataSerializer(serializers.ModelSerializer):
    settings = serializers.SerializerMethodField()
    data = serializers.SerializerMethodField()
    annotations = serializers.SerializerMethodField()
    selections = serializers.SerializerMethodField()
    selection_map = serializers.SerializerMethodField()

    def get_settings(self, curtain_data):
        if curtain_data.settings is None:
            return None
        return json.loads(curtain_data.settings)

    def get_data(self, curtain_data):
        if curtain_data.data is None:
            return None
        return json.loads(json.loads(curtain_data.data))

    def get_annotations(self, curtain_data):
        if curtain_data.annotations is None:
            return None
        return json.loads(curtain_data.annotations)

    def get_selections(self, curtain_data):
        if curtain_data.selections is None:
            return None
        return json.loads(curtain_data.selections)

    def get_selection_map(self, curtain_data):
        if curtain_data.selection_map is None:
            return None
        return json.loads(curtain_data.selection_map)
    class Meta:
        model = CurtainData
        fields = ['id', 'data', 'settings', 'host', 'link_id', 'analysis_group', 'created_at', 'updated_at', 'annotations', 'selections', 'selection_map']

class CollateSerializers(serializers.ModelSerializer):
    projects = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()

    def get_projects(self, collate):
        projects = collate.projects.all()
        if projects:
            return ProjectSerializer(projects, many=True).data
        else:
            return []

    def get_tags(self, collate):
        tags = collate.tags.all()
        if tags:
            return [{"name":i.name, "id": i.id} for i in tags]
        else:
            return []

    class Meta:
        model = Collate
        fields = ['id', 'title', 'greeting', 'projects', 'created_at', 'updated_at', 'settings', 'tags']

class CollateTagSerializer(serializers.ModelSerializer):

    class Meta:
        model = CollateTag
        fields = ['id', 'name', 'created_at', 'updated_at']

class UserSerializer(serializers.ModelSerializer):

    class Meta:
        model = User
        fields = ['id', 'username', 'is_staff']

class LabGroupSerializer(serializers.ModelSerializer):
    managers = serializers.SerializerMethodField()

    def get_managers(self, lab_group):
        return [user.id for user in lab_group.managing_members.all()]

    class Meta:
        model = LabGroup
        fields = ['id', 'name', 'created_at', 'updated_at', 'managers']

