from django.urls import path

from incidents import views

urlpatterns = [
    path("api/health/", views.HealthView.as_view()),
    path("api/auth/login/", views.LoginView.as_view()),
    path("api/auth/logout/", views.LogoutView.as_view()),
    path("api/services/", views.ServiceList.as_view()),
    path("api/services/<uuid:pk>/", views.ServiceDetail.as_view()),
    path("api/services/<uuid:pk>/key/", views.RotateKey.as_view()),
    path("api/services/<uuid:pk>/events/", views.IngestEvent.as_view()),
    path("api/services/<uuid:pk>/history/", views.ServiceEvents.as_view()),
    path("api/services/<uuid:pk>/summary/", views.ServiceSummary.as_view()),
    path("api/incidents/", views.IncidentList.as_view()),
    path("api/incidents/<uuid:pk>/", views.IncidentDetail.as_view()),
    path("api/incidents/<uuid:pk>/events/", views.IncidentEvents.as_view()),
    path("api/incidents/<uuid:pk>/reports/", views.IncidentReports.as_view()),
]
