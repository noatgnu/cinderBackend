import re
import requests
from django.core.management.base import BaseCommand
from cb.models import SubcellularLocation, HumanDisease


def parse_human_disease_file(filename=None):
    entries = []
    entry = None
    if not filename:
        url = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/humdisease.txt"
        response = requests.get(url)
        file = response.text.split("\n")
    else:
        file = open(filename, 'rt')

    for line in file:
        line = line.strip()

        if line.startswith("//"):
            if entry:
                entry.save()
                entry = None

        elif line.startswith("ID"):
            entry = HumanDisease()
            entry.identifier = line[5:].strip()
        elif line.startswith("AC") and entry:
            entry.accession = line[5:].strip()
        elif line.startswith("AR") and entry:
            entry.acronym = line[5:].strip()
        elif line.startswith("DE") and entry:
            if not entry.definition:
                entry.definition = ""
            entry.definition += (line[5:].strip() + " ")
        elif line.startswith("SY") and entry:
            if not entry.synonyms:
                entry.synonyms = ""
            entry.synonyms += (line[5:].strip() + "; ")
        elif line.startswith("DR") and entry:
            if not entry.cross_references:
                entry.cross_references = ""
            entry.cross_references = line[5:].strip()
        elif line.startswith("HI") and entry:
            if not entry.is_a:
                entry.is_a = ""
            entry.is_a += (line[5:].strip() + "; ")
        elif line.startswith("HP") and entry:
            if not entry.part_of:
                entry.part_of = ""
            entry.part_of += (line[5:].strip() + "; ")
        elif line.startswith("KW") and entry:
            if not entry.keywords:
                entry.keywords = ""
            entry.keywords += (line[5:].strip() + "; ")
    if not isinstance(file, list):
        file.close()

    return entries

class Command(BaseCommand):
    help = 'Load UniProt controlled vocabulary subcellular location data into the database.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str, nargs='?', help='The path to the species data file.')

    def handle(self, *args, **options):
        file_path = options.get('file')
        HumanDisease.objects.all().delete()
        parse_human_disease_file(file_path)
