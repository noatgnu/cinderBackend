import csv
import hashlib
import io
import json
import os
import re
import subprocess
import uuid
from typing import List, Dict, Optional

import numpy as np
import pandas as pd
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from curtainutils.client import CurtainClient, CurtainUniprotData
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField, SearchHeadline, SearchVector
from django.db import models
from django.db.models import Func
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

class Abs(Func):
    function = 'ABS'


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
    species = models.ForeignKey("Species", on_delete=models.CASCADE, related_name="projects", blank=True, null=True)

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
    analysis_group_type_choices = [
        ('proteomics', 'Proteomics'),
        ('ptm', 'Post-translational Modification'),
        ('proteogenomics', 'Proteogenomics'),
        ('metabolomics', 'Metabolomics'),
        ('lipidomics', 'Lipidomics'),
        ('glycomics', 'Glycomics'),
        ('glycoproteomics', 'Glycoproteomics'),
    ]
    analysis_group_type = models.CharField(max_length=255, choices=analysis_group_type_choices, default='proteomics')
    curtain_link = models.CharField(max_length=255, blank=True, null=True)

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
        ('copy_number', 'Copy Number'),
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
    extra_data = models.TextField(blank=True, null=True)

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
    log2_fc = models.FloatField(default=0.6)
    log10_p_value = models.FloatField(default=1.31)
    search_mode_choices = [
        ('full', "Full text"),
        ('gene', "Gene names"),
        ('uniprot', "UniProt Accession IDs"),
        ('pi', "Primary IDs")
    ]
    search_mode = models.CharField(max_length=255, choices=search_mode_choices, default='full')
    failed = models.BooleanField(default=False)
    species = models.ForeignKey("Species", on_delete=models.CASCADE, related_name="search_sessions", blank=True, null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def search_data(self):
        self.pending = False
        self.in_progress = True
        self.save()
        analysis_groups = self.analysis_groups.all()
        if self.species:
            analysis_groups = analysis_groups.filter(project__species=self.species)
        if analysis_groups.exists():
            files = ProjectFile.objects.filter(analysis_group__in=self.analysis_groups.all(), file_category__in=["df"])
        else:
            files = ProjectFile.objects.filter(file_category__in=["df"])
        files = files.filter(
            file_contents__search_vector=self.search_term
        ).annotate(
            headline=SearchHeadline(
                'file_contents__content', self.search_term, start_sel="<b>", stop_sel="</b>", highlight_all=True)
        ).distinct()
        term_headline_file_dict = {}
        found_terms = []
        results = []

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
        channel_layer = get_channel_layer()
        count_found_files = len([f for f in term_headline_file_dict])
        current_progress = 0
        async_to_sync(channel_layer.group_send)(
            f"search_{self.session_id}", {
                "type": "search_message", "message": {
                    "type": "search_status",
                    "status": "in_progress",
                    "id": self.id,
                    "found_files": count_found_files,
                    "current_progress": current_progress,
                }})

        primary_id_analysis_group_result_map = {}
        for f in term_headline_file_dict:
            related_files = term_headline_file_dict[f]['file'].analysis_group.project_files.all().exclude(id=f)
            result_in_file = []
            pi_list = []
            async_to_sync(channel_layer.group_send)(
                f"search_{self.session_id}", {
                    "type": "search_message", "message": {
                        "type": "search_status",
                        "status": "in_progress",
                        "id": self.id,
                        "found_files": count_found_files,
                        "current_progress": current_progress+1,
                    }})
            term_contexts = term_headline_file_dict[f]['term_contexts']

            for result in self.extract_result(f, term_contexts, term_headline_file_dict):
                if result.primary_id not in pi_list:
                    pi_list.append(result.primary_id)
                if result.primary_id not in primary_id_analysis_group_result_map:
                    primary_id_analysis_group_result_map[result.primary_id] = {}
                if result.file.analysis_group.id not in primary_id_analysis_group_result_map[result.primary_id]:
                    primary_id_analysis_group_result_map[result.primary_id][result.file.analysis_group.id] = {}
                if result.comparison_label not in primary_id_analysis_group_result_map[result.primary_id][result.file.analysis_group.id]:
                    primary_id_analysis_group_result_map[result.primary_id][result.file.analysis_group.id][result.comparison_label] = result
                else:
                    primary_id_analysis_group_result_map[result.primary_id][result.file.analysis_group.id][result.comparison_label] += f",{result.search_term}"
            for related in related_files:
                with related.file.open('rt') as infile:
                    first_line_of_file = infile.readline()
                    first_line_header = csv.reader([first_line_of_file], delimiter=related.get_delimiter())
                    column_headers_map = {h: i for i, h in enumerate(next(first_line_header))}
                    if related.extra_data:
                        extra_data = json.loads(related.extra_data)
                        if "primary_id_col" in extra_data:
                            primary_id_col_index = column_headers_map[extra_data["primary_id_col"]]
                            for line in infile:
                                line_data = next(csv.reader([line], delimiter=related.get_delimiter()))
                                primary_id = line_data[primary_id_col_index]
                                if primary_id in pi_list:
                                    if related.file_category == "searched":
                                        gene_name = ""
                                        uniprot_id = ""
                                        if "gene_name_col" in extra_data:
                                            if extra_data["gene_name_col"]:
                                                gene_name_col_index = column_headers_map[extra_data["gene_name_col"]]
                                                gene_name = line_data[gene_name_col_index]
                                        if "uniprot_id_col" in extra_data:
                                            if extra_data["uniprot_id_col"]:
                                                uniprot_col_index = column_headers_map[extra_data["uniprot_id_col"]]
                                                uniprot_id = line_data[uniprot_col_index]
                                        searched_data = []
                                        sample_annotation = SampleAnnotation.objects.filter(file=related).first()
                                        if sample_annotation:
                                            annotation = json.loads(sample_annotation.annotations)
                                            for a in annotation:
                                                if a["Sample"] in column_headers_map:
                                                    sample_col_index = column_headers_map[a["Sample"]]
                                                    if line_data[sample_col_index] != "":
                                                        searched_data.append({"Sample": a["Sample"], "Condition": a["Condition"],
                                                                          "Value": float(line_data[sample_col_index])})
                                                    else:
                                                        searched_data.append({"Sample": a["Sample"], "Condition": a["Condition"],
                                                                          "Value": None})
                                        search_result = SearchResult(
                                            search_term="",
                                            file=related,
                                            session=self,
                                            analysis_group=related.analysis_group,
                                            gene_name=gene_name,
                                            uniprot_id=uniprot_id,
                                            primary_id=primary_id,
                                            searched_data=json.dumps(searched_data).replace("NaN", "null")
                                        )
                                        if primary_id in primary_id_analysis_group_result_map:
                                            if related.analysis_group.id in primary_id_analysis_group_result_map[primary_id]:
                                                for comparison_label in primary_id_analysis_group_result_map[primary_id][related.analysis_group.id]:
                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][comparison_label].searched_data = search_result.searched_data
                                        #result_in_file.append(search_result)
                                    elif related.file_category == "df":
                                        comparison_matrix = ComparisonMatrix.objects.filter(file=related).first()
                                        if comparison_matrix.matrix:
                                            matrix = json.loads(comparison_matrix.matrix)
                                            for m in matrix:
                                                log2_fc = None
                                                log10_p = None
                                                if line_data[column_headers_map[m["fold_change_col"]]] != "":
                                                    log2_fc = float(line_data[column_headers_map[m["fold_change_col"]]])
                                                if line_data[column_headers_map[m["p_value_col"]]] != "":
                                                    log10_p = float(line_data[column_headers_map[m["p_value_col"]]])
                                                if log2_fc and log10_p:
                                                    if self.apply_fc_pvalue_filter(log2_fc, log10_p):
                                                        sr = SearchResult(
                                                            search_term="",
                                                            file=related,
                                                            session=self,
                                                            analysis_group=related.analysis_group,
                                                            condition_A=m["condition_A"],
                                                            condition_B=m["condition_B"],
                                                            log2_fc=log2_fc,
                                                            log10_p=log10_p,
                                                        )
                                                        if "comparison_col" in m:
                                                            if m["comparison_col"] in column_headers_map:
                                                                sr.comparison_label = line_data[column_headers_map[m["comparison_col"]]]
                                                                if m["comparison_label"]:
                                                                    sr.comparison_label += f"({m['comparison_label']})"
                                                            else:
                                                                sr.comparison_label = m["comparison_label"]
                                                        else:
                                                            sr.comparison_label = m["comparison_label"]
                                                        if primary_id in primary_id_analysis_group_result_map:
                                                            if related.analysis_group.id in primary_id_analysis_group_result_map[primary_id]:
                                                                if sr.comparison_label in primary_id_analysis_group_result_map[primary_id][related.analysis_group.id]:
                                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][sr.comparison_label].log2_fc = sr.log2_fc
                                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][sr.comparison_label].log10_p = sr.log10_p
                                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][sr.comparison_label].comparison_label = sr.comparison_label
                                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][sr.comparison_label].condition_A = sr.condition_A
                                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][sr.comparison_label].condition_B = sr.condition_B
                                                                else:
                                                                    primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][sr.comparison_label] = sr
                                                        #result_in_file.append(sr)

                                    elif related.file_category == "copy_number":
                                        if "copy_number_col" in extra_data and "rank_col" in extra_data:
                                            copy_number_col_index = column_headers_map[extra_data["copy_number_col"]]
                                            rank_col_index = column_headers_map[extra_data["rank_col"]]
                                            copy_number = float(line_data[copy_number_col_index])
                                            rank = int(line_data[rank_col_index])
                                            sr = SearchResult(
                                                search_term="",
                                                file=related,
                                                session=self,
                                                analysis_group=related.analysis_group,
                                                copy_number=copy_number,
                                                rank=rank,
                                            )
                                            if primary_id in primary_id_analysis_group_result_map:
                                                if related.analysis_group.id in primary_id_analysis_group_result_map[primary_id]:
                                                    for comparison_label in primary_id_analysis_group_result_map[primary_id][related.analysis_group.id]:
                                                        primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][comparison_label].copy_number = sr.copy_number
                                                        primary_id_analysis_group_result_map[primary_id][related.analysis_group.id][comparison_label].rank = sr.rank
                                            #result_in_file.append(sr)

            current_progress += 1
            #results.extend(result_in_file)
        for primary_id in primary_id_analysis_group_result_map:
            for analysis_group_id in primary_id_analysis_group_result_map[primary_id]:
                for comparison_label in primary_id_analysis_group_result_map[primary_id][analysis_group_id]:
                    results.append(primary_id_analysis_group_result_map[primary_id][analysis_group_id][comparison_label])
        SearchResult.objects.bulk_create(results)
        self.in_progress = False
        self.completed = True
        self.save()

    def extract_result(self, f, term_contexts, term_headline_file_dict):
        if term_contexts:
            file = term_headline_file_dict[f]['file']
            search_result_dict = {}
            # for term in term_contexts:
            #
            #     if term not in search_result_dict:
            #
            #         search_result = SearchResult.objects.create(search_term=term,
            #                                                 #headline_results=json.dumps(list(set(term_contexts[term]))),
            #                                                 file=file,
            #                                                 session=self,
            #                                                 analysis_group=file.analysis_group
            #                                                 )
            #         search_result_dict[term] = search_result

            line_term_already_found = {term: [] for term in term_contexts}
            first_line_of_file = ""
            column_headers_map = {}
            with file.file.open('rt') as infile:
                first_line_of_file = infile.readline()
                first_line_header = csv.reader([first_line_of_file], delimiter=file.get_delimiter())
                column_headers_map = {h: i for i, h in enumerate(next(first_line_header))}
            for result in self.get_contexts(file, term_contexts):
                found_term = result["term"].lower()
                if file.extra_data:
                    extra_data = json.loads(file.extra_data)
                    for search_result in self.extract_result_data(column_headers_map, file, found_term, result):
                        gene_name = ""
                        primary_id = ""
                        uniprot_id = ""
                        if "gene_name_col" in extra_data:
                            if extra_data["gene_name_col"]:
                                gene_name_col_index = column_headers_map[extra_data["gene_name_col"]]
                                gene_name = result["context"][gene_name_col_index]
                        if "primary_id_col" in extra_data:
                            if extra_data["primary_id_col"]:
                                primary_id_col_index = column_headers_map[extra_data["primary_id_col"]]
                                primary_id = result["context"][primary_id_col_index]
                        if "uniprot_id_col" in extra_data:
                            if extra_data["uniprot_id_col"]:
                                uniprot_col_index = column_headers_map[extra_data["uniprot_id_col"]]
                                uniprot_id = result["context"][uniprot_col_index]
                        search_result.gene_name = gene_name
                        search_result.primary_id = primary_id
                        search_result.uniprot_id = uniprot_id

                        if self.search_mode == "gene":
                            if "gene_name_col" in extra_data:
                                if gene_name:
                                    if found_term in gene_name.lower():
                                        yield search_result

                        elif self.search_mode == "uniprot":
                            if "uniprot_col" in extra_data:
                                if uniprot_id:
                                    if found_term in uniprot_id.lower():
                                        yield search_result
                        elif self.search_mode == "pi":
                            if "primary_id_col" in extra_data:
                                if primary_id:
                                    if found_term in primary_id.lower():
                                        yield search_result
                        else:
                            yield search_result


    def extract_result_data(self, column_headers_map, file, found_term, result):
        # print(file.file_category)
        if file.file_category == "df":
            comparison_matrix = ComparisonMatrix.objects.filter(file=file).first()
            if comparison_matrix:
                if comparison_matrix.matrix:
                    matrix = json.loads(comparison_matrix.matrix)
                    # print(matrix)
                    for m in matrix:
                        # print(result["context"])
                        log2_fc = None
                        if result["context"][column_headers_map[m["fold_change_col"]]] != "":
                            log2_fc = float(result["context"][column_headers_map[m["fold_change_col"]]])
                        # print(log2_fc)
                        log10_p = None
                        if result["context"][column_headers_map[m["p_value_col"]]] != "":
                            log10_p = float(result["context"][column_headers_map[m["p_value_col"]]])
                        if log2_fc and log10_p:
                            if self.apply_fc_pvalue_filter(log2_fc, log10_p):
                                sr = SearchResult(
                                    search_term=found_term,
                                    file=file,
                                    session=self,
                                    analysis_group=file.analysis_group,
                                    condition_A=m["condition_A"],
                                    condition_B=m["condition_B"],
                                    log2_fc=log2_fc,
                                    log10_p=log10_p,
                                )
                                if "comparison_col" in m:
                                    if m["comparison_col"] in column_headers_map:
                                        label = result["context"][column_headers_map[m["comparison_col"]]]
                                        print(label, m["comparison_label"])
                                        if m["comparison_label"]:
                                            if label == m['comparison_label']:
                                                sr.comparison_label = m['comparison_label']

                                    else:
                                        sr.comparison_label = m["comparison_label"]
                                else:
                                    sr.comparison_label = m["comparison_label"]
                                if sr.comparison_label:
                                    if len(sr.comparison_label) > 0:
                                        yield sr
        else:
            sr = SearchResult(
                search_term=found_term,
                file=file,
                session=self,
                analysis_group=file.analysis_group,
            )
            sample_annotation = SampleAnnotation.objects.filter(file=file).first()
            if sample_annotation:
                annotation = json.loads(sample_annotation.annotations)
                searched_data = []
                #print(annotation)
                for a in annotation:
                    #print(result["context"])

                    if a["Sample"] in column_headers_map:
                        sample_col_index = column_headers_map[a["Sample"]]
                        if result["context"][sample_col_index] != "":
                            searched_data.append({"Sample": a["Sample"], "Condition": a["Condition"],
                                                  "Value": float(result["context"][sample_col_index])})
                        else:
                            searched_data.append({"Sample": a["Sample"], "Condition": a["Condition"],
                                                  "Value": None})
                if searched_data and len(searched_data) > 0:
                    sr.searched_data = json.dumps(searched_data).replace("NaN", "null")
                    yield sr

    def get_contexts(self, file: ProjectFile, term_contexts: Dict[str, List[str]]):
        with file.file.open('rt') as infile:
            if os.name == "nt":
                for rid, line in enumerate(infile, 1):
                    line = line.strip()
                    if line:
                        for t in term_contexts:
                            match = re.search(r"(?<!\S)(?<!-|\w)(;)*{0}(?!\w)(?!\S)".format(t), line)
                            if match:
                                delimiter = file.get_delimiter()
                                yield {"row": rid, "term": t, "context": next(csv.reader([line], delimiter=delimiter, quotechar='"'))}
            else:
                for t in self.search_file(file.file.path, term_contexts):
                    # ignore header row
                    if t["row"] > 1:
                        row = t["row"]
                        delimiter = file.get_delimiter()
                        yield {"row": row, "term": t['term'], "context": next(csv.reader([t['context']], delimiter=delimiter, quotechar='"'))}

    def apply_fc_pvalue_filter(self, log2_fc: float, log10_p: float):
        return self.log2_fc <= abs(log2_fc) and log10_p >= self.log10_p_value


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
    #headline_results = models.TextField(blank=True, null=True)
    #search_results = models.TextField(blank=True, null=True)
    #search_count = models.IntegerField(default=0)
    file = models.ForeignKey(ProjectFile, on_delete=models.CASCADE, related_name='search_results', blank=True, null=True)
    session = models.ForeignKey(SearchSession, on_delete=models.CASCADE, related_name='search_results', blank=True, null=True)
    analysis_group = models.ForeignKey(AnalysisGroup, on_delete=models.CASCADE, related_name='search_results', blank=True, null=True)
    condition_A = models.CharField(max_length=255, blank=True, null=True)
    condition_B = models.CharField(max_length=255, blank=True, null=True)
    comparison_label = models.CharField(max_length=255, blank=True, null=True)
    log2_fc = models.FloatField(blank=True, null=True)
    log10_p = models.FloatField(blank=True, null=True)
    searched_data = models.TextField(blank=True, null=True)
    primary_id = models.CharField(max_length=255, blank=True, null=True)
    gene_name = models.CharField(max_length=255, blank=True, null=True)
    uniprot_id = models.CharField(max_length=255, blank=True, null=True)
    copy_number = models.FloatField(blank=True, null=True)
    rank = models.IntegerField(blank=True, null=True)

    class Meta:
        ordering = ['created_at']
        app_label = 'cb'

    def __str__(self):
        return self.search_term


class Species(models.Model):
    """ A model to store UniProt species information"""
    code = models.CharField(max_length=255)
    taxon = models.IntegerField()
    official_name = models.CharField(max_length=255)
    common_name = models.CharField(max_length=255, blank=True, null=True)
    synonym = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        app_label = 'cb'
        ordering = ['official_name']


class CurtainData(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    host = models.CharField(max_length=255)
    link_id = models.CharField(max_length=255)
    analysis_group = models.ForeignKey(AnalysisGroup, on_delete=models.CASCADE, related_name='curtain_data', blank=True, null=True)
    data = models.TextField(blank=True, null=True)
    settings = models.TextField(blank=True, null=True)
    annotations = models.TextField(blank=True, null=True)
    selections = models.TextField(blank=True, null=True)
    selection_map = models.TextField(blank=True, null=True)

    class Meta:
        app_label = 'cb'
        ordering = ['created_at']

    def __str__(self):
        return f"{self.link_id} - {self.host} - Created: {self.created_at}"

    def __repr__(self):
        return f"{self.link_id} - {self.host} - Created: {self.created_at}"

    def parse_curtain_data(self, data: dict, diff_df: pd.DataFrame, primary_id_col: str, fold_change_col: str, p_value_col: str, comparison_col: str = None):
        curtain_data = CurtainUniprotData(data["extraData"]["uniprot"])
        def parse_data(row: pd.Series, curtain_data: CurtainUniprotData, primary_id_col: str):
            uniprot = curtain_data.get_uniprot_data_from_pi(row[primary_id_col])
            if isinstance(uniprot, pd.Series):
                row["Gene Names"] = uniprot["Gene Names"]
                row["Entry"] = uniprot["Entry"]
            return row

        diff_df = diff_df.apply(lambda x: parse_data(x, curtain_data, primary_id_col), axis=1)
        self.settings = json.dumps(data["settings"])
        diff_df = diff_df[[primary_id_col, fold_change_col, p_value_col, "Gene Names", "Entry", comparison_col]]
        columns_rename_dict = {primary_id_col: "Primary ID", fold_change_col: "Fold Change", p_value_col: "P-value"}
        if comparison_col:
            columns_rename_dict[comparison_col] = "Comparison"
        diff_df.rename(columns=columns_rename_dict,
                       inplace=True)
        self.data = json.dumps(diff_df.to_json(orient="records"))
        self.annotations = json.dumps([data["annotatedData"][k] for k in data["annotatedData"]])
        self.selections = json.dumps(data["selectionsName"])
        self.selection_map = json.dumps(data["selectionsMap"])
        self.save()

    def get_curtain_data(self, session_id=None):
        client = CurtainClient(self.host)
        channel_layer = get_channel_layer()
        if session_id:
            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "curtain_status",
                        "status": "in_progress",
                        "id": self.id,
                        "message": "Downloading data from Curtain"
                    }})
        data = client.download_curtain_session(self.link_id)
        if session_id:
            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "curtain_status",
                        "status": "in_progress",
                        "id": self.id,
                        "message": "Parsing data from Curtain"
                    }})
        differential_analysis_file = self.analysis_group.project_files.filter(file_category="df").first()

        if data["processed"]:
            diff_df = pd.read_csv(io.StringIO(data["processed"]), sep=None)
        else:
            diff_df = pd.read_csv(differential_analysis_file.file.path, sep=differential_analysis_file.get_delimiter())
        primary_id_col = data["differentialForm"]["_primaryIDs"]
        fold_change_col = data["differentialForm"]["_foldChange"]
        p_value_col = data["differentialForm"]["_significant"]
        print(diff_df.shape)
        if data["differentialForm"]["_comparison"]:
            comparison_col = data["differentialForm"]["_comparison"]
            if data["differentialForm"]["_comparisonSelect"]:
                comparison_label = data["differentialForm"]["_comparisonSelect"]
                diff_df[comparison_col] = diff_df[comparison_col].astype(str)
                diff_df = diff_df[diff_df[comparison_col].isin(comparison_label)]
        print(diff_df.shape)
        if data["differentialForm"]["_transformFC"]:
            diff_df[fold_change_col] = np.log2(diff_df[fold_change_col])
        if data["differentialForm"]["_transformSignificant"]:
            diff_df[p_value_col] = -np.log10(diff_df[p_value_col])
        if data["differentialForm"]["_reverseFoldChange"]:
            diff_df[fold_change_col] = -diff_df[fold_change_col]
        self.parse_curtain_data(data, diff_df, primary_id_col, fold_change_col, p_value_col, data["differentialForm"]["_comparison"])

    def compose_analysis_group_from_curtain_data(self, analysis_group: AnalysisGroup, session_id=None):
        client = CurtainClient(self.host)
        channel_layer = get_channel_layer()
        if session_id:
            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "curtain_status",
                        "status": "in_progress",
                        "id": self.id,
                        "message": "Downloading data from Curtain"
                    }})
        data = client.download_curtain_session(self.link_id)
        if session_id:
            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "curtain_status",
                        "status": "in_progress",
                        "id": self.id,
                        "message": "Parsing data from Curtain"
                    }})
        diff_file = pd.read_csv(io.StringIO(data["processed"]), sep=None)
        searched_file = pd.read_csv(io.StringIO(data["raw"]), sep=None)
        media_folder = os.path.join(settings.MEDIA_ROOT, "user_files")
        if not os.path.exists(media_folder):
            os.makedirs(media_folder)
        diff_file_path = os.path.join(media_folder, f"{uuid.uuid4().hex}.diff.txt")
        if data["differentialForm"]["_transformFC"]:
            diff_file[data["differentialForm"]["_foldChange"]] = np.log2(diff_file[data["differentialForm"]["_foldChange"]])
        if data["differentialForm"]["_transformSignificant"]:
            diff_file[data["differentialForm"]["_significant"]] = -np.log10(diff_file[data["differentialForm"]["_significant"]])
        if data["differentialForm"]["_reverseFoldChange"]:
            diff_file[data["differentialForm"]["_foldChange"]] = -diff_file[data["differentialForm"]["_foldChange"]]
        if data["differentialForm"]["_comparison"]:
            comparison_col = data["differentialForm"]["_comparison"]
            if comparison_col != "CurtainSetComparison":
                diff_file[comparison_col] = diff_file[comparison_col].astype(str)
        diff_file.to_csv(diff_file_path, sep="\t", index=False)
        searched_file_path = os.path.join(media_folder, f"{uuid.uuid4().hex}.searched.txt")
        searched_file.to_csv(searched_file_path, sep="\t", index=False)
        diff_file_extra_data = {
            "primary_id_col": data["differentialForm"]["_primaryIDs"],
            "gene_name_col": None,
            "uniprot_id_col": None,
            "peptide_seq_col": None,
            "modification_position_in_peptide_col": None,
            "modification_position_in_protein_col": None,
            "localization_prob_col": None,
        }

        diff_project_file = ProjectFile.objects.create(
            name=f"{analysis_group.name} - Differential Analysis.txt",
            description="Differential Analysis",
            file_category="df",
            file_type="txt",
            analysis_group=analysis_group,
            project=analysis_group.project,
            file=diff_file_path,
            load_file_content=True,
            extra_data=json.dumps(diff_file_extra_data)
        )
        diff_project_file.save_altered()
        searched_file_extra_data = {
            "primary_id_col": data["rawForm"]["_primaryIDs"],
            "gene_name_col": None,
            "uniprot_id_col": None,
        }
        searched_project_file = ProjectFile.objects.create(
            name=f"{analysis_group.name} - Searched Data.txt",
            description="Searched Data",
            file_category="searched",
            file_type="txt",
            analysis_group=analysis_group,
            project=analysis_group.project,
            file=searched_file_path,
            load_file_content=True,
            extra_data=json.dumps(searched_file_extra_data)
        )
        searched_project_file.save_altered()
        annotations = []
        for s in data["rawForm"]["_samples"]:
            if "sampleMap" in data["settings"]:
                if s in data["settings"]["sampleMap"]:
                    annotations.append({"Sample": s, "Condition": data["settings"]["sampleMap"][s]["condition"]})
                else:
                    splitted = s.split(".")
                    if len(splitted) > 1:
                        annotations.append({"Sample": s, "Condition": ".".join(splitted[0:len(splitted) - 1]) })
                    else:
                        annotations.append({"Sample": s, "Condition": s})
            else:
                splitted = s.split(".")
                if len(splitted) > 1:
                    annotations.append({"Sample": s, "Condition": ".".join(splitted[0:len(splitted)-1])})
                else:
                    annotations.append({"Sample": s, "Condition": s})

        SampleAnnotation.objects.create(
            name=f"{analysis_group.name} - Sample Annotations",
            analysis_group=analysis_group,
            file=searched_project_file,
            annotations=json.dumps(annotations)
        )

        if data["differentialForm"]["_comparison"] == "CurtainSetComparison" or data["differentialForm"]["_comparison"] == "":
            matrix = [
                {
                    "condition_A": "",
                    "condition_B": "",
                    "fold_change_col": data["differentialForm"]["_foldChange"],
                    "p_value_col": data["differentialForm"]["_significant"],
                    "comparison_col": "",
                    "comparison_label": "1"
                }
            ]
            comparison_matrix = ComparisonMatrix.objects.create(
                name=f"{analysis_group.name} - Comparison Matrix",
                analysis_group=analysis_group,
                file=diff_project_file,
                matrix=json.dumps(matrix)
            )

        else:
            matrix = []
            if "_comparisonSelect" in data["differentialForm"]:
                comparison_labels = data["differentialForm"]["_comparisonSelect"]
                for label in comparison_labels:
                    matrix.append(
                        {
                            "condition_A": "",
                            "condition_B": "",
                            "fold_change_col": data["differentialForm"]["_foldChange"],
                            "p_value_col": data["differentialForm"]["_significant"],
                            "comparison_col": data["differentialForm"]["_comparison"],
                            "comparison_label": label
                        }
                    )
            comparison_matrix = ComparisonMatrix.objects.create(
                name=f"{analysis_group.name} - Comparison Matrix",
                analysis_group=analysis_group,
                file=diff_project_file,
                matrix=json.dumps(matrix)
            )
        if session_id:
            async_to_sync(channel_layer.group_send)(
                f"curtain_{session_id}", {
                    "type": "curtain_message", "message": {
                        "type": "curtain_status",
                        "status": "in_progress",
                        "id": self.id,
                        "message": "Creating Analysis Group"
                    }})
        if data["differentialForm"]["_comparisonSelect"]:
            if data["differentialForm"]["_comparison"] != "CurtainSetComparison":
                comparison_label = data["differentialForm"]["_comparisonSelect"]
                diff_file = diff_file[diff_file[data["differentialForm"]["_comparison"]].isin(comparison_label)]
        self.parse_curtain_data(data,
                                diff_file,
                                data["differentialForm"]["_primaryIDs"],
                                data["differentialForm"]["_foldChange"],
                                data["differentialForm"]["_significant"],
                                data["differentialForm"]["_comparison"]
                                )






@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_auth_token(sender, instance=None, created=False, **kwargs):
    if created:
        Token.objects.create(user=instance)

@receiver(post_save, sender=ProjectFileContent)
def update_search_vector(sender, instance=None, created=False, **kwargs):
    if created:
        instance.search_vector = SearchVector("content")
        instance.save()
