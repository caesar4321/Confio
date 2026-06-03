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
