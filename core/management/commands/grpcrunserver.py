from django_grpc_framework.management.commands.grpcrunserver import Command as BaseCommand


class Command(BaseCommand):
    requires_system_checks = []