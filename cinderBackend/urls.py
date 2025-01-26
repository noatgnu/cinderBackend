"""
URL configuration for cinderBackend project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from rest_framework import routers
from rest_framework.authtoken.views import obtain_auth_token

from cb.views import DataChunkedUploadView, LogoutView, FrontEndTemplateView, set_csrf
from cb.viewsets import ProjectViewSet, ProjectFileViewSet, AnalysisGroupViewSet, SampleAnnotationViewSet, \
    ComparisonMatrixViewSet, SearchResultViewSet, SearchSessionViewSet, SpeciesViewSet, CollateViewSet, \
    CollateTagViewSet, UserViewSet, LabGroupViewSet, TissueViewSet, SubcellularLocationViewSet, HumanDiseaseViewSet, \
    MetadataColumnViewSet, SourceFileViewSet, MSUniqueVocabulariesViewSet, UnimodViewSets

router = routers.DefaultRouter()
router.register(r'projects', ProjectViewSet)
router.register(r'project_files', ProjectFileViewSet)
router.register(r'analysis_groups', AnalysisGroupViewSet)
router.register(r"sample_annotations", SampleAnnotationViewSet)
router.register(r"comparison_matrices", ComparisonMatrixViewSet)
router.register(r"search", SearchSessionViewSet)
router.register(r"search_results", SearchResultViewSet)
router.register(r"species", SpeciesViewSet)
router.register(r"collates", CollateViewSet)
router.register(r"collate_tags", CollateTagViewSet)
router.register(r"users", UserViewSet)
router.register(r"lab_groups", LabGroupViewSet)
router.register(r"tissues", TissueViewSet)
router.register(r"subcellular_locations", SubcellularLocationViewSet)
router.register(r"human_diseases", HumanDiseaseViewSet)
router.register(r"metadata_columns", MetadataColumnViewSet)
router.register(r"source_files", SourceFileViewSet)
router.register(r"ms_vocab", MSUniqueVocabulariesViewSet)
router.register(r"unimod", UnimodViewSets)

urlpatterns = [
    path('admin/', admin.site.urls),
    path('api/', include(router.urls)),
    path('api/token-auth/', obtain_auth_token),
    path('api/chunked_upload/', DataChunkedUploadView.as_view(), name='chunked_upload'),
    path('api/chunked_upload/<uuid:pk>/', DataChunkedUploadView.as_view(), name='chunkedupload-detail'),
    path('api/logout/', LogoutView.as_view(), name='logout'),
    path('api/frontend_template/', FrontEndTemplateView.as_view(), name='frontend_template'),
    path("api/set-csrf/", set_csrf, name="set_csrf"),
    path('accounts/', include('allauth.urls')),
    path("_allauth/", include("allauth.headless.urls")),
]
