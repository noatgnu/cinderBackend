import re
import requests
from django.core.management.base import BaseCommand
from cb.models import SubcellularLocation, Tissue


def parse_tissue_file(filename=None):
    entries = []
    entry = None

    if not filename:
        url = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/tisslist.txt"
        response = requests.get(url)
        file = response.text.split("\n")
    else:
        file = open(filename, 'rt')

    for line in file:
        if line.startswith("//"):
            if entry:
                entry.save()
                entry = None

        elif line.startswith("ID"):
            entry = Tissue()
            entry.identifier = line[5:].strip()
        elif line.startswith("AC") and entry:
            entry.accession = line[5:].strip()
        elif line.startswith("SY") and entry:
            if not entry.synonyms:
                entry.synonyms = ""
            entry.synonyms += (line[5:].strip() + "; ")
        elif line.startswith("DR") and entry:
            if not entry.cross_references:
                entry.cross_references = ""
            entry.cross_references += (line[5:].strip() + "; ")

    if not isinstance(file, list):
        file.close()

    return entries

class Command(BaseCommand):
    help = 'Load UniProt controlled vocabulary subcellular location data into the database.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str, nargs='?',  help='The path to the species data file.')

    def handle(self, *args, **options):
        file_path = options.get('file')
        Tissue.objects.all().delete()
        parse_tissue_file(file_path)
