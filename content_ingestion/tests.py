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

        with patch.dict(ai_client._DISPATCH, {'openai': lambda prompt, system='': f'openai:{prompt}'}):
            self.assertEqual(ai_client.complete_text('hi', provider='chatgpt'), 'openai:hi')

    def test_complete_text_passes_system_prompt(self):
        from content_ingestion import ai_client

        with patch.dict(ai_client._DISPATCH, {'openai': lambda prompt, system='': f'{system}|{prompt}'}):
            self.assertEqual(
                ai_client.complete_text('hi', provider='openai', system='SYS'),
                'SYS|hi',
            )

    @override_settings(
        OPENAI_API_KEY='x',
        CLAUDE_API_KEY='', GEMINI_API_KEY='', GROK_API_KEY='', DEEPSEEK_API_KEY='',
    )
    def test_debate_with_single_provider_just_answers(self):
        from content_ingestion import ai_client

        with patch.dict(ai_client._DISPATCH, {'openai': lambda prompt, system='': 'only-answer'}):
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


class SmartContextTests(SimpleTestCase):
    def test_compose_prompt_puts_message_before_history(self):
        from content_ingestion.management.commands.telegram_ai_listener import _compose_prompt

        out = _compose_prompt('hola', 'Ana: hi\nBob: yo', 'mensaje previo')
        self.assertLess(out.index('Mensaje a responder'), out.index('Conversación reciente'))
        self.assertIn('mensaje previo', out)
        self.assertIn('hola', out)

    def test_compose_prompt_without_context(self):
        from content_ingestion.management.commands.telegram_ai_listener import _compose_prompt

        out = _compose_prompt('hola', '', '')
        self.assertIn('hola', out)
        self.assertNotIn('Conversación reciente', out)

    def test_media_label_detects_video_and_none(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import _media_label

        video = types.SimpleNamespace(
            media=True, video=True, video_note=None, photo=None, voice=None, audio=None,
            file=types.SimpleNamespace(name='demo.mp4', mime_type='video/mp4'),
        )
        self.assertEqual(_media_label(video), '[video: demo.mp4]')
        self.assertEqual(_media_label(types.SimpleNamespace(media=None)), '')

    def test_display_name_fallbacks(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import _display_name

        self.assertEqual(_display_name(types.SimpleNamespace(first_name='Ana', last_name='Pérez')), 'Ana Pérez')
        self.assertEqual(_display_name(None, 42), 'usuario 42')


class ToolLoopTests(SimpleTestCase):
    def test_parse_tool_call(self):
        from content_ingestion.ai_agent import _parse_tool_call

        tools = {'get_chat_videos': lambda a: '', 'search_knowledge': lambda a: ''}
        self.assertEqual(_parse_tool_call('TOOL get_chat_videos', tools), ('get_chat_videos', ''))
        self.assertEqual(
            _parse_tool_call('TOOL search_knowledge precios koywe', tools),
            ('search_knowledge', 'precios koywe'),
        )
        self.assertEqual(_parse_tool_call('```\nTOOL get_chat_videos\n```', tools), ('get_chat_videos', ''))
        self.assertIsNone(_parse_tool_call('Hola, ¿cómo estás?', tools))
        self.assertIsNone(_parse_tool_call('TOOL unknown x', tools))

    def test_run_with_tools_executes_then_answers(self):
        from content_ingestion import ai_agent

        replies = iter(['TOOL get_chat_videos', 'Tienes 2 videos: A y B.'])

        def fake_complete(prompt, provider=None, *, system=None):
            return next(replies)

        called = {}

        def videos_tool(args):
            called['hit'] = True
            return 'A, B'

        with patch('content_ingestion.ai_agent.complete_text', side_effect=fake_complete):
            out = ai_agent.run_with_tools('¿qué videos hay?', 'gemini', 'SYS', {'get_chat_videos': videos_tool})
        self.assertIn('videos', out)
        self.assertTrue(called.get('hit'))

    def test_run_with_tools_no_tools_is_plain_completion(self):
        from content_ingestion import ai_agent

        with patch('content_ingestion.ai_agent.complete_text', return_value='plain') as mock:
            out = ai_agent.run_with_tools('hi', 'gemini', 'SYS', {})
        self.assertEqual(out, 'plain')
        mock.assert_called_once()


class KnowledgeCorpusTests(SimpleTestCase):
    def test_corpus_empty_when_repo_missing(self):
        from content_ingestion import ai_context

        ai_context._CACHE['sig'] = None
        with override_settings(CONFIO_AI_REPO_PATH='/nonexistent/confioai', CONFIO_AI_CONTEXT_ROOT='docs'):
            self.assertEqual(ai_context.load_knowledge_corpus(), '')

    def test_corpus_reads_markdown(self):
        import os
        import tempfile
        from content_ingestion import ai_context

        with tempfile.TemporaryDirectory() as d:
            docs = os.path.join(d, 'docs', 'strategy')
            os.makedirs(docs)
            with open(os.path.join(docs, 'plan.md'), 'w', encoding='utf-8') as fh:
                fh.write('Lanzar primero en Venezuela.')
            ai_context._CACHE['sig'] = None
            with override_settings(CONFIO_AI_REPO_PATH=d, CONFIO_AI_CONTEXT_ROOT='docs'):
                corpus = ai_context.load_knowledge_corpus()
        self.assertIn('Lanzar primero en Venezuela', corpus)
