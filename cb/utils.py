import json
import os
import re
import subprocess

import cb
#from cb.models import ComparisonMatrix
from cb.serializers import ProjectSerializer, ProjectFileSerializer





# def extract_found_data(analysis, files):
#     file_results = []
#     project_results = []
#     found_terms_dict = {}
#     for i in files:
#         if i.id not in found_terms_dict:
#             found_terms_dict[i.id] = []
#         term_contexts = i.get_search_items_from_headline()
#         if term_contexts:
#             for t in term_contexts:
#                 if t not in found_terms_dict[i.id]:
#                     found_terms_dict[i.id].append(t)
#             i.headline = json.dumps(term_contexts)
#             if i.project not in project_results:
#                 project_results.append(i.project)
#             file_results.append(ProjectFileSerializer(i).data)
#     found_lines_dict = {}
#     analysis_file_map = {}
#     found_line_term_map = {}
#     for i in files:
#         if i.id not in found_lines_dict:
#             found_lines_dict[i.id] = []
#             found_line_term_map[i.id] = {}
#             ana = analysis.filter(project_files=i)
#             if os.name == "nt":
#                 with i.file.open('rt') as f:
#                     for rid, line in enumerate(f, 1):
#                         line = line.strip()
#                         if line:
#                             for t in found_terms_dict[i.id]:
#                                 match = re.search(r"(?<!\S)(?<!-|\w)(;)*{0}(?!\w)(?!\S)".format(t), line)
#                                 if match:
#                                     if rid not in found_terms_dict[i.id]:
#                                         found_lines_dict[i.id].append(rid)
#                                     if rid not in found_line_term_map[i.id]:
#                                         found_line_term_map[i.id][rid] = []
#                                     found_line_term_map[i.id][rid].append(t)
#             else:
#                 for t in search_file(i.file.path, found_terms_dict[i.id]):
#                     if t[0] not in found_lines_dict[i.id]:
#                         found_lines_dict[i.id].append(t[0])
#                     if t[0] not in found_line_term_map[i.id]:
#                         found_line_term_map[i.id][t[0]] = []
#                     found_line_term_map[i.id][t[0]].append(t[1])
#             if ana:
#                 if i.id not in analysis_file_map:
#                     analysis_file_map[i.id] = {}
#                 analysis_dict = {}
#
#                 for a in ana:
#                     analysis_dict[a.id] = {"df": {}, "searched": {},
#                                            "comparison_matrix": [], "sample_annotation": {}}
#
#                     if i.file_category == 'df':
#                         for l in i.get_file_line(found_lines_dict[i.id]):
#                             analysis_dict[a.id]["df"][l[0]] = l[1]
#                         if a.comparison_matrices:
#                             cm: ComparisonMatrix = a.comparison_matrices.first()
#                             if cm.matrix:
#                                 analysis_dict[a.id]["comparison_matrix"] = json.loads(cm.matrix)
#                         for project_file in a.project_files.all():
#                             if project_file.file_category == 'searched':
#                                 if project_file.id in analysis_file_map:
#                                     analysis_file_map[project_file.id][a.id]['df'] = analysis_dict[a.id]['df']
#                                     analysis_file_map[project_file.id][a.id]['comparison_matrix'] = \
#                                     analysis_dict[a.id]['comparison_matrix']
#                                     analysis_dict[a.id]["searched"] = analysis_file_map[project_file.id][a.id][
#                                         'searched']
#                                     analysis_dict[a.id]["sample_annotation"] = \
#                                     analysis_file_map[project_file.id][a.id]['sample_annotation']
#                     if i.file_category == 'searched':
#                         for l in i.get_file_line(found_lines_dict[i.id]):
#                             analysis_dict[a.id]["searched"][l[0]] = l[1]
#                         if a.sample_annotations:
#                             sa = a.sample_annotations.first()
#                             if sa.annotation:
#                                 analysis_dict[a.id]["sample_annotation"] = json.loads(sa.annotation)
#                         for project_file in a.project_files.all():
#                             if project_file.file_category == 'df':
#                                 if project_file.id in analysis_file_map:
#                                     analysis_file_map[project_file.id][a.id]['searched'] = analysis_dict[a.id][
#                                         'searched']
#                                     analysis_file_map[project_file.id][a.id]['sample_annotation'] = \
#                                     analysis_dict[a.id]['sample_annotation']
#                                     analysis_dict[a.id]["df"] = analysis_file_map[project_file.id][a.id]['df']
#                                     analysis_dict[a.id]["comparison_matrix"] = \
#                                     analysis_file_map[project_file.id][a.id]['comparison_matrix']
#                 analysis_file_map[i.id] = analysis_dict
#     project_results = [ProjectSerializer(p, many=False).data for p in project_results]
#     return analysis_file_map, file_results, found_line_term_map, found_lines_dict, project_results