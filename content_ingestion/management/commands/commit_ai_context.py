from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from content_ingestion.context_repo import ContextRepoError, write_commit_and_push_context
from content_ingestion.models import AIContextCategory, AIContextDocument


class Command(BaseCommand):
    help = 'Write an AI context Markdown document to the ConfioAI repo, commit it, and optionally push.'

    def add_arguments(self, parser):
        parser.add_argument('--category', default=AIContextCategory.DECISION_LOG, choices=AIContextCategory.values)
        parser.add_argument('--title', required=True)
        parser.add_argument('--body')
        parser.add_argument('--file', help='Read body from a Markdown/text file.')
        parser.add_argument('--slug')
        parser.add_argument('--no-push', action='store_true')

    def handle(self, *args, **options):
        body = options.get('body') or ''
        if options.get('file'):
            body = Path(options['file']).read_text(encoding='utf-8')
        body = body.strip()
        if not body:
            raise CommandError('Provide --body or --file.')

        document = AIContextDocument.objects.create(
            category=options['category'],
            title=options['title'],
            slug=options.get('slug') or slugify(options['title'])[:100] or 'untitled',
            body=body,
        )
        try:
            document = write_commit_and_push_context(document, push=not options['no_push'])
        except ContextRepoError as exc:
            document.mark_failed(str(exc))
            raise CommandError(str(exc)) from exc

        self.stdout.write(
            self.style.SUCCESS(
                f'{document.status}: {document.relative_path} {document.commit_sha}'.strip()
            )
        )
