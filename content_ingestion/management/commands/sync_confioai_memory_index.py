from django.core.management.base import BaseCommand, CommandError

from content_ingestion.ai_context import _memory_chunks
from content_ingestion.memory_index import sync_chunks


class Command(BaseCommand):
    help = 'Synchronize canonical ConfioAI Markdown chunks into the RDS pgvector index.'

    def handle(self, *args, **options):
        try:
            result = sync_chunks(_memory_chunks())
        except Exception as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(
            self.style.SUCCESS(
                'ConfioAI memory index synchronized: '
                f'{result["total"]} total, {result["inserted"]} embedded, '
                f'{result["deleted"]} deleted, {result["unchanged"]} unchanged.'
            )
        )

