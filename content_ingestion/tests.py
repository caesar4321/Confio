from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase, override_settings

from .models import AIContextCategory
from .views import enqueue_ai_context_commit


class AIContextCommitViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @override_settings(DEBUG=False, CONTENT_INGESTION_API_SECRET='secret')
    def test_rejects_unauthorized_request(self):
        request = self.factory.post(
            '/api/content-ingestion/ai-context/',
            data='{"title":"Koywe focus","body":"Keep launch focus on Koywe."}',
            content_type='application/json',
        )
        response = enqueue_ai_context_commit(request)
        self.assertEqual(response.status_code, 401)

    @override_settings(DEBUG=False, CONTENT_INGESTION_API_SECRET='secret')
    @patch('content_ingestion.views.commit_ai_context_document_task')
    @patch('content_ingestion.views.AIContextDocument')
    def test_authorized_request_creates_document_and_enqueues_commit(self, document_model, task):
        document_model.objects.create.return_value.pk = 42
        task.delay.return_value.id = 'task-123'
        request = self.factory.post(
            '/api/content-ingestion/ai-context/',
            data='{"title":"Koywe focus","body":"Keep launch focus on Koywe.","category":"decision-log"}',
            content_type='application/json',
            HTTP_AUTHORIZATION='Bearer secret',
        )
        response = enqueue_ai_context_commit(request)
        self.assertEqual(response.status_code, 200)
        document_model.objects.create.assert_called_once()
        task.delay.assert_called_once_with(42, True)

    @override_settings(DEBUG=True, CONTENT_INGESTION_API_SECRET='')
    def test_rejects_unknown_category(self):
        request = self.factory.post(
            '/api/content-ingestion/ai-context/',
            data='{"title":"Bad","body":"Body","category":"not-real"}',
            content_type='application/json',
        )
        response = enqueue_ai_context_commit(request)
        self.assertEqual(response.status_code, 400)

    def test_expected_categories_include_social_video_buckets(self):
        self.assertIn('videos', AIContextCategory.values)
        self.assertIn('social-stats', AIContextCategory.values)


class AIProviderRoutingTests(SimpleTestCase):
    def test_normalize_aliases(self):
        from content_ingestion.ai_client import normalize_provider

        self.assertEqual(normalize_provider('chatgpt'), 'openai')
        self.assertEqual(normalize_provider('GPT'), 'openai')
        self.assertEqual(normalize_provider('anthropic'), 'claude')
        self.assertEqual(normalize_provider('xai'), 'grok')
        self.assertEqual(normalize_provider('google'), 'gemini')

    def test_normalize_rejects_unknown(self):
        from content_ingestion.ai_client import AIClientError, normalize_provider

        with self.assertRaises(AIClientError):
            normalize_provider('llama')

    @override_settings(
        OPENAI_API_KEY='x', CLAUDE_API_KEY='y',
        GEMINI_API_KEY='', GROK_API_KEY='', DEEPSEEK_API_KEY='',
    )
    def test_configured_providers_reflects_keys(self):
        from content_ingestion.ai_client import configured_providers

        self.assertEqual(configured_providers(), ['openai', 'claude'])

    def test_complete_text_routes_by_alias(self):
        from content_ingestion import ai_client

        with patch.dict(ai_client._DISPATCH, {'openai': lambda prompt: f'openai:{prompt}'}):
            self.assertEqual(ai_client.complete_text('hi', provider='chatgpt'), 'openai:hi')

    @override_settings(
        OPENAI_API_KEY='x',
        CLAUDE_API_KEY='', GEMINI_API_KEY='', GROK_API_KEY='', DEEPSEEK_API_KEY='',
    )
    def test_debate_with_single_provider_just_answers(self):
        from content_ingestion import ai_client

        with patch.dict(ai_client._DISPATCH, {'openai': lambda prompt: 'only-answer'}):
            out = ai_client.debate('q')
        self.assertIn('ChatGPT', out)
        self.assertIn('only-answer', out)


class CommandParsingTests(SimpleTestCase):
    def test_split_command(self):
        from content_ingestion.management.commands.telegram_ai_listener import _split_command

        self.assertEqual(_split_command('hello there'), (None, 'hello there'))
        self.assertEqual(_split_command('/claude how are you'), ('/claude', 'how are you'))
        self.assertEqual(_split_command('/debate'), ('/debate', ''))
        self.assertEqual(_split_command('/CLAUDE@SomeBot hi'), ('/claude', 'hi'))
