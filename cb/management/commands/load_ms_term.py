import requests
from django.core.management.base import BaseCommand
from cb.models import MSUniqueVocabularies
import pronto
from io import BytesIO

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

    #sub_1000548 = ms["MS:1000548"].subclasses().to_set()
    #for term in sub_1000548:
    #    MSUniqueVocabularies.objects.create(
    #        accession=term.id,
    #        name=term.name,
    #        definition = term.definition,
    #        term_type="sample attribute"
    #    )

    sub_1000133 = ms["MS:1000133"].subclasses().to_set()
    for term in sub_1000133:
        MSUniqueVocabularies.objects.create(
            accession=term.id,
            name=term.name,
            definition = term.definition,
            term_type="dissociation method"
        )

    response = requests.get("https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000514/hierarchicalDescendants")
    data = response.json()
    for term in data["_embedded"]["terms"]:
        MSUniqueVocabularies.objects.create(
            accession=term["obo_id"],
            name=term["label"],
            definition = term["description"],
            term_type="sample attribute"
        )
    if data["page"]["totalPages"] > 1:
        for i in range(1, data["page"]["totalPages"]+1):
            response = requests.get("https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000514/hierarchicalDescendants?page="+str(i)+"&size=20")
            data2 = response.json()
            if "_embedded" in data2:
                for term in data2["_embedded"]["terms"]:
                    MSUniqueVocabularies.objects.create(
                        accession=term["obo_id"],
                        name=term["label"],
                        definition = term["description"],
                        term_type="sample attribute"
                    )


class Command(BaseCommand):
    help = 'Load MS instrument data into the database.'

    def handle(self, *args, **options):
        MSUniqueVocabularies.objects.all().delete()
        load_instrument()
