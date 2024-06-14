from django.db import models


class MockSearchVectorField(models.TextField):
    def db_type(self, connection):
        return 'search_vector'


class MockGinIndex(models.Index):
    def create_sql(self, model, schema_editor, using=""):
        return super().create_sql(model, schema_editor, using="")

    def db_type(self, connection):
        return None