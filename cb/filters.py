import django_filters
from .models import Unimod

class UnimodFilter(django_filters.FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='startswith')

    class Meta:
        model = Unimod
        fields = ['name']