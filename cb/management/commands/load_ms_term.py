import requests
from django.core.management.base import BaseCommand
from cb.models import MSUniqueVocabularies
import pronto

def load_instrument():
    ms = pronto.Ontology.from_obo_library("ms.obo")

    # get only leaf nodes that is subclass of MS:1000031
    sub_1000031 = ms["MS:1000031"].subclasses().to_set()
    for term in sub_1000031:
        if term.is_leaf():
            MSUniqueVocabularies.objects.create(
                accession=term.id,
                name=term.name,
                definition = term.definition,
                term_type="instrument"
            )
    sub_1001045 = ms["MS:1001045"].subclasses().to_set()
    for term in sub_1001045:
        if term.is_leaf():
            MSUniqueVocabularies.objects.create(
                accession=term.id,
                name=term.name,
                definition = term.definition,
                term_type="cleavage agent"
            )

    sub_1000548 = ms["MS:1000548"].subclasses().to_set()
    for term in sub_1000548:
        MSUniqueVocabularies.objects.create(
            accession=term.id,
            name=term.name,
            definition = term.definition,
            term_type="sample attribute"
        )

    sub_1000133 = ms["MS:1000133"].subclasses().to_set()
    for term in sub_1000133:
        MSUniqueVocabularies.objects.create(
            accession=term.id,
            name=term.name,
            definition = term.definition,
            term_type="dissociation method"
        )



class Command(BaseCommand):
    help = 'Load MS instrument data into the database.'

    def handle(self, *args, **options):
        MSUniqueVocabularies.objects.all().delete()
        load_instrument()
