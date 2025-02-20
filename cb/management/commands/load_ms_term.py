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

    load_ebi_resource("https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000514/hierarchicalDescendants")

    load_ebi_resource("https://www.ebi.ac.uk/ols4/api/ontologies/clo/terms", 1000, "cell line")

    load_ebi_resource("https://www.ebi.ac.uk/ols4/api/ontologies/efo/terms/http%253A%252F%252Fwww.ebi.ac.uk%252Fefo%252FEFO_0009090/hierarchicalDescendants", 1000, "Enrichment process")

    load_ebi_resource("https://www.ebi.ac.uk/ols4/api/ontologies/pride/terms/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPRIDE_0000550/hierarchicalDescendants", 1000, "Fractionation method")
def load_ebi_resource(base_url: str, size: int = 20, term_type: str = "sample attribute"):
    response = requests.get(base_url+"?page=0&size="+str(size))
    data = response.json()
    for term in data["_embedded"]["terms"]:
        MSUniqueVocabularies.objects.create(
            accession=term["obo_id"],
            name=term["label"],
            definition = term["description"],
            term_type=term_type
        )
    if data["page"]["totalPages"] > 1:
        for i in range(1, data["page"]["totalPages"]+1):
            response = requests.get(base_url+"?page="+str(i)+"&size="+str(size))
            data2 = response.json()
            if "_embedded" in data2:
                for term in data2["_embedded"]["terms"]:
                    MSUniqueVocabularies.objects.create(
                        accession=term["obo_id"],
                        name=term["label"],
                        definition = term["description"],
                        term_type=term_type
                    )


class Command(BaseCommand):
    help = 'Load MS instrument data into the database.'

    def handle(self, *args, **options):
        MSUniqueVocabularies.objects.all().delete()
        load_instrument()
