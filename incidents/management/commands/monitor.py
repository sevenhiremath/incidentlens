import time

from django.core.management.base import BaseCommand, CommandError
from django.db import close_old_connections

from incidents.monitor import check_all


class Command(BaseCommand):
    help = "Check enabled services. Run one monitor process for this version."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")
        parser.add_argument("--interval", type=int, default=30)

    def handle(self, *args, **options):
        if not 5 <= options["interval"] <= 60:
            raise CommandError("Use an interval between 5 and 60 seconds.")
        try:
            while True:
                started = time.monotonic()
                close_old_connections()
                count = check_all()
                self.stdout.write(f"Checked {count} service(s).")
                if options["once"]:
                    break
                time.sleep(max(0, options["interval"] - (time.monotonic() - started)))
        except KeyboardInterrupt:
            self.stdout.write("Monitor stopped.")
