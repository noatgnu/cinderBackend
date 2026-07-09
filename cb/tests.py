import shutil
import tempfile

from django.contrib.auth.models import User
from django.contrib.postgres.search import SearchHeadline
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings

from cb.models import ProjectFile, ProjectFileContent, Project, SearchSession


def create_temporary_file():
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

    def test_load_file_chunks_by_byte_size(self):
        """
        A CSV row with no whitespace becomes a single token under the whitespace
        split in load_file(). Without byte-size based chunking, a large enough
        row (or 50,000-token group) produces a tsvector input over Postgres'
        1,048,575 byte limit and load_file() raises an OperationalError.
        """
        media_root = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, media_root, ignore_errors=True)
        media_root_override = override_settings(MEDIA_ROOT=media_root)
        media_root_override.enable()
        self.addCleanup(media_root_override.disable)

        row = ",".join(str(i) for i in range(300000))
        large_content = (row + "\n") * 3

        file = ProjectFile.objects.create(
            name='Large File',
            description='Test Description',
            file_type='csv',
            file_category='df',
            load_file_content=True,
        )
        file.file.save('large.csv', SimpleUploadedFile('large.csv', large_content.encode('utf-8')))
        file.load_file()

        contents = list(ProjectFileContent.objects.filter(file=file))
        assert contents

        seen_values = []
        for content in contents:
            assert len(content.content.encode('utf-8')) <= 500_000
            for value in content.content.replace("\n", " ").split(","):
                for sub_value in value.split(" "):
                    if sub_value:
                        int(sub_value)
                        seen_values.append(sub_value)

        assert seen_values.count("0") == 3
        assert seen_values.count("299999") == 3

        file.delete()

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




