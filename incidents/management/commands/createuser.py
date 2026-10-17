import os
from getpass import getpass

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Create a local dashboard account. The password is entered privately."

    def add_arguments(self, parser):
        parser.add_argument("--username")
        parser.add_argument(
            "--password-env", help="Read a test account password from this env variable."
        )

    def handle(self, *args, **options):
        username = (options["username"] or input("Username: ")).strip()
        if not username or get_user_model().objects.filter(username=username).exists():
            raise CommandError("Choose a new, non-empty username.")
        env_name = options["password_env"]
        if env_name and env_name not in os.environ:
            raise CommandError("The named password environment variable is missing.")
        password = (
            os.environ[env_name] if env_name else getpass("Password (at least 10 characters): ")
        )
        if len(password) < 10:
            raise CommandError("Use at least 10 characters.")
        if not env_name and password != getpass("Confirm password: "):
            raise CommandError("Passwords did not match.")
        try:
            validate_password(password)
        except ValidationError as exc:
            raise CommandError(" ".join(exc.messages)) from exc
        user = get_user_model()(username=username)
        try:
            user.full_clean(exclude=["password"])
        except ValidationError as exc:
            raise CommandError(str(exc)) from exc
        user.set_password(password)
        user.save()
        self.stdout.write(self.style.SUCCESS("Account created. You can log in through Streamlit."))
