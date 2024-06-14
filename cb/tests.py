from django.contrib.auth.models import User
from django.contrib.postgres.search import SearchHeadline
from django.test import TestCase

from cb.models import ProjectFile, ProjectFileContent, Project, SearchSession


# Create your tests here.

def create_temporary_file():
    from django.core.files.base import ContentFile
    from django.core.files.uploadedfile import SimpleUploadedFile

    file = SimpleUploadedFile("file.txt", b"This is a test content")
    return file


class TestProjectFileContent(TestCase):
    def test_project_file_content(self):
        project_file_content = ProjectFileContent.objects.create(
            content='This is a test content',
        )
        results = ProjectFileContent.objects.filter(search_vector="test").annotate(
            headline=SearchHeadline('content', "test", start_sel="<b>", stop_sel="</b>",
                                    highlight_all=True)).distinct()
        assert results.exists()
        for i in results:
            assert '<b>test</b> content' in i.headline

    def test_project_file(self):
        file = ProjectFile.objects.create(
            name='Test File',
            description='Test Description',
            file_type='txt',
            file_category='df',
            load_file_content=True,
        )
        project_file_content = ProjectFileContent.objects.create(
            content='This is a test content',
            file=file
        )

        results = ProjectFile.objects.filter(file_contents__search_vector="test").annotate(
            headline=SearchHeadline('file_contents__content', "test", start_sel="<b>", stop_sel="</b>",
                                    highlight_all=True)).distinct()
        assert results.exists()
        for i in results:
            assert '<b>test</b> content' in i.headline
            result = i.get_search_items_from_headline()
            assert 'test' in result
            assert '<b>test</b> content' in result['test'][0]
            print(result)

    def test_project_file_multiple_content(self):
        file = ProjectFile.objects.create(
            name='Test File',
            description='Test Description',
            file_type='txt',
            file_category='df',
            load_file_content=True,
        )
        project_file_content = ProjectFileContent.objects.create(
            content='This is a test content.This is a test2 content',
            file=file
        )
        project_file_content = ProjectFileContent.objects.create(
            content='This is a test2 content',
            file=file
        )

        results = ProjectFile.objects.filter(file_contents__search_vector="test").annotate(
            headline=SearchHeadline('file_contents__content', "test", start_sel="<b>", stop_sel="</b>",
                                    highlight_all=True)).distinct()
        assert results.exists()
        for i in results:
            print(i.headline)


class TestProject(TestCase):
    def setUp(self):
        user = User.objects.create_user(
            username='test',
            password='test'
        )

    def test_project(self):
        user = User.objects.first()
        project = Project.objects.create(
            name='Test Project',
            description='Test Description',
            hash='test',
            metadata='test',
            global_id='test',
            temporary=False,
            encrypted=False,
            user=user
        )

        analysis_group = project.analysis_groups.create(
            name='Test Analysis Group',
            description='Test Description',
            phosphorylation=False
        )

        file = ProjectFile()
        file.name = 'Test File'
        file.description = 'Test Description'
        file.file_type = 'txt'
        file.file_category = 'df'
        file.load_file_content = True
        file.project = project
        file.analysis_group = analysis_group
        file.file = create_temporary_file()
        file.save()
        file.load_file()

        search_session = SearchSession.objects.create(
            search_term='test',
            user=user,
        )
        search_session.analysis_groups.add(analysis_group)
        search_session.search_data()
        for i in search_session.search_results.all():
            print(i.search_results)

        file.delete()




