import secrets

from django.contrib.auth import authenticate
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils.dateparse import parse_date
from rest_framework import generics, status
from rest_framework.authtoken.models import Token
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .logic import RevisionConflict, ingest_error, save_report
from .models import Incident, Service
from .security import key_digest, new_service_key
from .serializers import (
    ErrorInputSerializer,
    EventSerializer,
    IncidentSerializer,
    ReportInputSerializer,
    ReportSerializer,
    ServiceSerializer,
)


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "login"

    def get_authenticate_header(self, request):
        return "Token"

    def post(self, request):
        username = request.data.get("username", "")
        password = request.data.get("password", "")
        if not isinstance(username, str) or not isinstance(password, str):
            raise ValidationError("Username and password must be strings.")
        user = authenticate(username=username, password=password)
        if user is None:
            raise AuthenticationFailed("Username or password is incorrect.")
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "username": user.username})


class LogoutView(APIView):
    def post(self, request):
        request.auth.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ServiceList(generics.ListCreateAPIView):
    serializer_class = ServiceSerializer

    def get_queryset(self):
        return Service.objects.filter(owner=self.request.user).prefetch_related("incidents")

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                serializer.save(owner=self.request.user)
        except IntegrityError as exc:
            raise ValidationError("A service with that name and environment exists.") from exc


class ServiceDetail(generics.RetrieveUpdateAPIView):
    serializer_class = ServiceSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return Service.objects.filter(owner=self.request.user)

    def perform_update(self, serializer):
        # Use the same lock as the monitor; do not overwrite counters during an edit.
        try:
            with transaction.atomic():
                current = Service.objects.select_for_update().get(pk=serializer.instance.pk)
                changed_fields = set(serializer.validated_data)
                if (
                    "enabled" in serializer.validated_data
                    and current.enabled != serializer.validated_data["enabled"]
                ):
                    current.consecutive_failures = 0
                    current.consecutive_successes = 0
                    current.first_failure_at = None
                    current.last_checked_at = None
                    current.last_check_ok = None
                    current.last_latency_ms = None
                    changed_fields.update(
                        [
                            "consecutive_failures",
                            "consecutive_successes",
                            "first_failure_at",
                            "last_checked_at",
                            "last_check_ok",
                            "last_latency_ms",
                        ]
                    )
                for field, value in serializer.validated_data.items():
                    setattr(current, field, value)
                current.save(update_fields=list(changed_fields))
                serializer.instance = current
        except IntegrityError as exc:
            raise ValidationError("A service with that name and environment exists.") from exc


class RotateKey(APIView):
    def post(self, request, pk):
        service = get_object_or_404(Service, pk=pk, owner=request.user)
        raw, digest = new_service_key()
        Service.objects.filter(pk=service.pk).update(key_digest=digest)
        return Response({"service_key": raw, "detail": "Copy it now. Only its hash is stored."})


class IngestEvent(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get_authenticate_header(self, request):
        return "ServiceKey"

    def post(self, request, pk):
        service = Service.objects.filter(pk=pk).first()
        raw = request.headers.get("X-Service-Key", "")
        if (
            not service
            or not service.key_digest
            or not secrets.compare_digest(service.key_digest, key_digest(raw))
        ):
            raise AuthenticationFailed("Invalid service key.")
        serializer = ErrorInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event, created = ingest_error(service.pk, serializer.validated_data)
        return Response(
            {"id": event.id, "duplicate": not created},
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class IncidentList(generics.ListAPIView):
    serializer_class = IncidentSerializer

    def get_queryset(self):
        queryset = Incident.objects.filter(service__owner=self.request.user).select_related(
            "service"
        )
        service = self.request.query_params.get("service")
        if service:
            from uuid import UUID

            try:
                UUID(service)
            except ValueError as exc:
                raise ValidationError({"service": "Use a valid service UUID."}) from exc
            queryset = queryset.filter(service_id=service)
        selected_status = self.request.query_params.get("status")
        if selected_status:
            if selected_status not in Incident.Status.values:
                raise ValidationError({"status": "Use open, recovered, or closed."})
            queryset = queryset.filter(status=selected_status)
        query = self.request.query_params.get("search", "")[:100]
        if query:
            queryset = queryset.filter(
                Q(service__name__icontains=query) | Q(confirmed_cause__icontains=query)
            )
        for parameter, lookup in [
            ("since", "detected_at__date__gte"),
            ("until", "detected_at__date__lte"),
        ]:
            raw = self.request.query_params.get(parameter)
            if raw:
                try:
                    value = parse_date(raw)
                except ValueError:
                    value = None
                if value is None:
                    raise ValidationError({parameter: "Use YYYY-MM-DD."})
                queryset = queryset.filter(**{lookup: value})
        return queryset


class IncidentDetail(generics.RetrieveUpdateAPIView):
    serializer_class = IncidentSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_queryset(self):
        return Incident.objects.filter(service__owner=self.request.user).select_related("service")

    def perform_update(self, serializer):
        # Only editable fields are written, so a simultaneous recovery is preserved.
        for field, value in serializer.validated_data.items():
            setattr(serializer.instance, field, value)
        serializer.instance.save(update_fields=list(serializer.validated_data))


class IncidentEvents(generics.ListAPIView):
    serializer_class = EventSerializer

    def get_queryset(self):
        incident = get_object_or_404(
            Incident,
            pk=self.kwargs["pk"],
            service__owner=self.request.user,
        )
        return incident.events.all()


class IncidentReports(generics.ListAPIView):
    serializer_class = ReportSerializer

    def get_incident(self):
        return get_object_or_404(Incident, pk=self.kwargs["pk"], service__owner=self.request.user)

    def get_queryset(self):
        return self.get_incident().reports.all()

    def post(self, request, pk):
        incident = self.get_incident()
        serializer = ReportInputSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            report, created = save_report(incident.pk, request.user, **serializer.validated_data)
        except RevisionConflict as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_409_CONFLICT)
        return Response(
            ReportSerializer(report).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )


class ServiceEvents(generics.ListAPIView):
    serializer_class = EventSerializer

    def get_queryset(self):
        service = get_object_or_404(Service, pk=self.kwargs["pk"], owner=self.request.user)
        return service.events.order_by("-occurred_at", "-received_at")


class HealthView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        return Response({"status": "ok", "version": "0.1.0", "report_mode": "template"})
