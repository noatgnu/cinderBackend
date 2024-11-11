from django.core.management.base import BaseCommand
from cb.models import Unimod
import pronto
import requests
from io import BytesIO

def load_instrument():
    response = requests.get("https://www.unimod.org/obo/unimod.obo")
    ms = pronto.Ontology(BytesIO(response.content))

    sub_0 = ms["UNIMOD:0"].subclasses().to_set()
    for term in sub_0:
        if term.is_leaf():
            data = []
            for x in term.xrefs:
                data.append({"id": x.id, "description": x.description})

            Unimod.objects.create(
                accession=term.id,
                name=term.name,
                definition = term.definition,
                additional_data = data
            )



class Command(BaseCommand):
    help = 'Load MS instrument data into the database.'

    def handle(self, *args, **options):
        Unimod.objects.all().delete()
        load_instrument()
