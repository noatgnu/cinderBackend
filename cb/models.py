import csv
import hashlib
import json
import os
import re
import subprocess
from typing import List, Dict, Optional

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField, SearchHeadline, SearchVector
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token
from django.conf import settings

import cb


# if settings.DATABASES['default']['ENGINE'] == 'django.db.backends.sqlite3':
#     from cb.mocks import MockSearchVectorField as SearchVectorField
#     from cb.mocks import MockGinIndex as GinIndex
# else:
#     from django.contrib.postgres.indexes import GinIndex
#     from django.contrib.postgres.search import SearchVectorField, SearchHeadline


# Project model represents a project in the system.
# Each project has a name, description, hash, metadata, global_id, temporary status, user, encrypted status, created_at and updated_at fields.
class Project(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    hash = models.CharField(max_length=255)
    metadata = models.TextField(blank=True, null=True)
    global_id = models.CharField(max_length=255)
    temporary = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='projects')
    encrypted = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.name

# AnalysisGroup model represents a group of analysis in the system.
# Each AnalysisGroup has a name, description, project, created_at and updated_at fields.

class AnalysisGroup(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='analysis_groups', blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    ptm = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.name

# ProjectFile model represents a file in a project.
# Each ProjectFile has a name, description, hash, file_category, file_type, file, analysis_group, path, created_at, updated_at, load_file_content, metadata, project fields.

class ProjectFile(models.Model):
    name = models.CharField(max_length=255)
    description = models.TextField()
    hash = models.CharField(max_length=255, default='')
    file_category_choices = [
        ('searched', 'MS Search Output'),
        ('df', 'Differential Analysis'),
        ('raw', 'Raw Data'),
        ('other', 'Other'),
    ]
    file_type_choices = [
        ('txt', "Tabulated text"),
        ('csv', "Comma-separated values"),
        ('tsv', "Tab-separated values"),
        ('other', "Other"),
    ]
    file_category = models.CharField(max_length=255, choices=file_category_choices, default='other')
    file_type = models.CharField(max_length=255, choices=file_type_choices, default='other')
    file = models.FileField(upload_to='user_files/', blank=True, null=True)
    analysis_group = models.ForeignKey(AnalysisGroup, on_delete=models.CASCADE, related_name='project_files', blank=True, null=True)
    path = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    load_file_content = models.BooleanField(default=False)
    metadata = models.TextField(blank=True, null=True)
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='files', blank=True, null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.name

    def delete(self, using=None, keep_parents=False):
        self.file.delete()
        super().delete(using, keep_parents)

    def save(self, *args, **kwargs):
        return super().save(*args, **kwargs)

    def save_altered(self, *args, **kwargs):
        # calculate sha256 hash of the file
        if self.file:
            hasher = hashlib.sha256()
            with self.file.open('rb') as afile:
                for chunk in iter(lambda: afile.read(4096), b""):
                    hasher.update(chunk)
            data_hash = hasher.hexdigest()
            if data_hash != self.hash:
                self.hash = data_hash
                if self.load_file_content:
                    self.load_file()

        return super().save(*args, **kwargs)

    def load_file(self):
        """
        Method to load the content of the file into the database
        """
        content = self.file_contents.all()
        if content.exists():
            content.delete()
        with open(self.file.path, 'rt') as file:
            content = file.read()
            content = re.split(r"[\s\n\t]", content)
            chunk_size = 50000
            for i in range(0, len(content), chunk_size):
                if i + chunk_size < len(content):
                    ProjectFileContent.objects.create(file=self, content=" ".join(content[i:i + chunk_size]))
                else:
                    ProjectFileContent.objects.create(file=self, content=" ".join(content[i:]))

    def remove_file_content(self):
        self.file_contents.all().delete()

    def get_search_items_from_headline(self) -> Optional[Dict[str, List[str]]]:
        if getattr(self, "headline", None):
            pattern = '(?<!\S)(?<!-|\w)(;)*<b>(\w+)'
            term_contexts = {}
            for match in re.finditer(pattern, self.headline):
                if match:
                    m = match.group(2)
                    if m not in term_contexts:
                        term_contexts[m] = []
                    start = match.start(0)
                    end = match.end(0)
                    # get a window of 10 words before and after the match
                    window = 20
                    start_window = start - window
                    end_window = end + window
                    if start_window < 0:
                        start_window = 0
                    if end_window > len(self.headline):
                        end_window = len(self.headline)
                    term_contexts[m].append(self.headline[start_window:end_window])

            return term_contexts
        else:
            return None

    def get_delimiter(self):
        if self.file_type == "csv":
            return ","
        elif self.file_type == "tsv":
            return "\t"
        elif self.file_type == "txt":
            return "\t"
        else:
            return None

    def get_file_line(self, line_numbers: list[int]):
        with self.file.open("rt") as f:
            line = f.readline()
            delimiter = self.get_delimiter()
            headers = line.rstrip().split(delimiter)
            for i, line in enumerate(f):
                if i > 0:
                    if i+1 in line_numbers:
                        line = line.rstrip()
                        data = line.split(delimiter)
                        yield i+1, dict(zip(headers, data))

# ProjectFileContent model represents a segment of text content from a file.
# Each ProjectFileContent has a file, content, created_at, updated_at, search_vector fields.
class ProjectFileContent(models.Model):
    """
    A model to store segments of text content from a file. A file would be broken down into multiple segments, each would become a ProjectFileContent object
    The model would be used to provide a way for searching through text content of loaded files utilizing postgres full text search.
    The model also hold a GIN index on the search_vector field to speed up search queries.
    """
    file = models.ForeignKey(ProjectFile, on_delete=models.CASCADE, related_name='file_contents', blank=True, null=True)
    content = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    search_vector = SearchVectorField(null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'
        indexes = [
            GinIndex(fields=["search_vector"])
        ]

    def __str__(self):
        if self.file:
            return self.file.name + " - " + str(self.created_at)
        return str(self.id)

    def set_search_vector(self):
        self.search_vector = SearchVector("content")
        self.save()

# ComparisonMatrix model represents a comparison matrix in the system.
# Each ComparisonMatrix has a name, analysis_group, matrix, created_at, updated_at fields.

class ComparisonMatrix(models.Model):
    name = models.CharField(max_length=255)
    analysis_group = models.ForeignKey(AnalysisGroup, on_delete=models.CASCADE, related_name='comparison_matrices', blank=True, null=True)
    matrix = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file = models.ForeignKey(ProjectFile, on_delete=models.CASCADE, related_name='comparison_matrices', blank=True, null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.name

# SampleAnnotation model represents a sample annotation in the system.
# Each SampleAnnotation has a name, analysis_group, annotations, created_at, updated_at fields.
class SampleAnnotation(models.Model):
    name = models.CharField(max_length=255)
    analysis_group = models.ForeignKey(AnalysisGroup, on_delete=models.CASCADE, related_name='sample_annotations', blank=True, null=True)
    annotations = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    file = models.ForeignKey(ProjectFile, on_delete=models.CASCADE, related_name='sample_annotations', blank=True, null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.name

class SearchSession(models.Model):
    """
    A model to store search sessions.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    search_term = models.CharField(max_length=255)
    session_id = models.CharField(max_length=255, blank=True, null=True)
    analysis_groups = models.ManyToManyField(AnalysisGroup, related_name='search_sessions', blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='search_sessions', blank=True, null=True)
    found_terms = models.TextField(blank=True, null=True)
    completed = models.BooleanField(default=False)
    pending = models.BooleanField(default=True)
    in_progress = models.BooleanField(default=False)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def search_data(self):
        self.pending = False
        self.in_progress = True
        self.save()
        files = ProjectFile.objects.filter(analysis_group__in=self.analysis_groups.all())
        files = files.filter(file_contents__search_vector=self.search_term).annotate(headline=SearchHeadline('file_contents__content', self.search_term, start_sel="<b>", stop_sel="</b>", highlight_all=True)).distinct()
        term_headline_file_dict = {}
        found_terms = []
        for f in files:
            if f.id not in term_headline_file_dict:
                term_headline_file_dict[f.id] = {'file': f, 'term_contexts': {}}
            term_contexts = f.get_search_items_from_headline()
            for t in term_contexts:
                term = t.lower()
                if term not in term_headline_file_dict[f.id]['term_contexts']:
                    term_headline_file_dict[f.id]['term_contexts'][term] = []
                term_headline_file_dict[f.id]['term_contexts'][term].extend(term_contexts[t])
                if term not in found_terms:
                    found_terms.append(term)

        for f in term_headline_file_dict:
            term_contexts = term_headline_file_dict[f]['term_contexts']

            if term_contexts:
                file = term_headline_file_dict[f]['file']
                search_result_dict = {}
                for term in term_contexts:

                    if term not in search_result_dict:

                        search_result = SearchResult.objects.create(search_term=term,
                                                                headline_results=json.dumps(list(set(term_contexts[term]))),
                                                                file=file,
                                                                session=self,
                                                                analysis_group=file.analysis_group
                                                                )
                        search_result_dict[term] = search_result

                line_term_already_found = {term: [] for term in term_contexts}
                with file.file.open('rt') as infile:
                    if os.name == "nt":
                        for rid, line in enumerate(infile, 1):
                            line = line.strip()
                            if line:
                                for t in term_contexts:
                                    match = re.search(r"(?<!\S)(?<!-|\w)(;)*{0}(?!\w)(?!\S)".format(t), line)
                                    if match:
                                        delimiter = file.get_delimiter()
                                        line_term_already_found[t.lower()].append({"line": rid, "term": t, "context": next(csv.reader([line], delimiter=delimiter, quotechar='"'))})
                    else:
                        for t in self.search_file(file.file.path, term_contexts):
                            # ignore header row
                            if t["row"] > 1:
                                row = t["row"]
                                delimiter = file.get_delimiter()
                                line_term_already_found[t['term'].lower()].append({"line": row, "term": t['term'], "context": next(csv.reader([t['context']], delimiter=delimiter, quotechar='"'))})

                for k in line_term_already_found:
                    search_result = search_result_dict[k]
                    result_array = []
                    for i in line_term_already_found[k]:
                        result_array.append(i)
                    search_result.search_results = json.dumps(result_array)
                    search_result.search_count = len(result_array)
                    search_result.save()
        self.in_progress = False
        self.completed = True
        self.save()

    def search_file(self, filepath: str, terms: Dict[str, List[str]]):
        """
        A function that use search.sh script from cephalon to search for terms in a file
        """
        cephalon_path = os.path.dirname(cb.__file__)
        search_sh_path = os.path.join(cephalon_path, "search.sh").replace("\\", "/")
        filepath = filepath.replace('\\', '/')

        result = subprocess.run(['bash', search_sh_path, ','.join(terms), filepath], capture_output=True)
        print('bash', search_sh_path, ','.join(terms), filepath)
        data = result.stdout.decode("utf-8")
        for i in data.split("\n"):
            if i == "":
                break
            row = i.split(":")
            yield {"term": row[0].strip(), "row": int(row[1].strip()), "context": row[2]}




class SearchResult(models.Model):
    """
    A model to store search results.
    """
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    search_term = models.CharField(max_length=255)
    headline_results = models.TextField(blank=True, null=True)
    search_results = models.TextField(blank=True, null=True)
    search_count = models.IntegerField(default=0)
    file = models.ForeignKey(ProjectFile, on_delete=models.CASCADE, related_name='search_results', blank=True, null=True)
    session = models.ForeignKey(SearchSession, on_delete=models.CASCADE, related_name='search_results', blank=True, null=True)
    analysis_group = models.ForeignKey(AnalysisGroup, on_delete=models.CASCADE, related_name='search_results', blank=True, null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.search_term


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)

@receiver(post_save, sender=ProjectFileContent)
def update_search_vector(sender, instance=None, created=False, **kwargs):
    if created:
        instance.search_vector = SearchVector("content")
        instance.save()