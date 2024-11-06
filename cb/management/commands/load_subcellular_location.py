import re
import requests
from django.core.management.base import BaseCommand
from cb.models import SubcellularLocation

def parse_subcellular_location_file(filename=None):
    entries = []
    entry = None
    started = False
    if not filename:
        url = "https://ftp.uniprot.org/pub/databases/uniprot/current_release/knowledgebase/complete/docs/subcell.txt"
        response = requests.get(url)
        file = response.text.split("\n")
    else:
        file = open(filename, 'rt')

    for line in file:
        line = line.strip()
        if line.startswith("AN"):
            started = True
        if started:
            if line.startswith("//"):
                if entry:
                    entry.save()
                    entry = None

            elif line.startswith("ID"):
                entry = SubcellularLocation()
                entry.location_identifier = line[5:].strip()
            elif line.startswith("IT") and entry:
                entry.topology_identifier = line[5:].strip()
            elif line.startswith("IO") and entry:
                entry.orientation_identifier = line[5:].strip()
            elif line.startswith("AC") and entry:
                entry.accession = line[5:].strip()
            elif line.startswith("DE") and entry:
                if not entry.definition:
                    entry.definition = ""
                entry.definition += (line[5:].strip() + " ")
            elif line.startswith("SY") and entry:
                if not entry.synonyms:
                    entry.synonyms = ""
                entry.synonyms += (line[5:].strip() + "; ")
            elif line.startswith("SL") and entry:
                if not entry.content:
                    entry.content = ""
                entry.content = line[5:].strip()
            elif line.startswith("HI") and entry:
                if not entry.is_a:
                    entry.is_a = ""
                entry.is_a += (line[5:].strip() + "; ")
            elif line.startswith("HP") and entry:
                if not entry.part_of:
                    entry.part_of = ""
                entry.part_of += (line[5:].strip() + "; ")
            elif line.startswith("KW") and entry:
                entry.keyword = line[5:].strip()
            elif line.startswith("GO") and entry:
                if not entry.gene_ontology:
                    entry.gene_ontology = ""
                entry.gene_ontology += (line[5:].strip() + "; ")
            elif line.startswith("AN") and entry:
                if not entry.annotation:
                    entry.annotation = ""
                entry.annotation += (line[5:].strip() + " ")
            elif line.startswith("RX") and entry:
                if not entry.references:
                    entry.references = ""
                entry.references += (line[5:].strip() + "; ")
            elif line.startswith("WW") and entry:
                if not entry.links:
                    entry.links = ""
                entry.links += (line[5:].strip() + "; ")
    if not isinstance(file, list):
        file.close()

    return entries

class Command(BaseCommand):
    help = 'Load UniProt controlled vocabulary subcellular location data into the database.'

    def add_arguments(self, parser):
        parser.add_argument('file', type=str, nargs='?',  help='The path to the species data file.')

    def handle(self, *args, **options):
        file_path = options.get('file')
        SubcellularLocation.objects.all().delete()
        parse_subcellular_location_file(file_path)
