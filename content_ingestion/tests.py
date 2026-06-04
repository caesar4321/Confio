from unittest.mock import patch
from datetime import date

from django.test import RequestFactory, SimpleTestCase, override_settings

from .models import AIContextCategory, AIContextDocument
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


class AIContextRepoPathTests(SimpleTestCase):
    @override_settings(CONFIO_AI_CONTEXT_ROOT='docs')
    def test_video_documents_are_written_directly_under_videos(self):
        from content_ingestion.context_repo import _document_relative_path

        document = AIContextDocument(
            category=AIContextCategory.VIDEOS,
            title='Coreano, por qué usas la misma camiseta',
            slug='coreano-por-que-usas-la-misma-camiseta',
            body='Body',
        )

        self.assertEqual(
            str(_document_relative_path(document, date(2026, 6, 3))),
            'docs/videos/coreano-por-que-usas-la-misma-camiseta.md',
        )

    @override_settings(CONFIO_AI_CONTEXT_ROOT='docs')
    def test_video_documents_can_be_written_under_named_folder(self):
        from content_ingestion.context_repo import _document_relative_path

        document = AIContextDocument(
            category=AIContextCategory.VIDEOS,
            title='Un influencer coreano con esquizofrenia',
            slug='un-influencer-coreano-con-esquizofrenia',
            body='Body',
            metadata={'folder': 'Vida y filosofía'},
        )

        self.assertEqual(
            str(_document_relative_path(document, date(2026, 6, 3))),
            'docs/videos/Vida y filosofía/un-influencer-coreano-con-esquizofrenia.md',
        )

    @override_settings(CONFIO_AI_CONTEXT_ROOT='docs')
    def test_non_video_documents_keep_year_bucket(self):
        from content_ingestion.context_repo import _document_relative_path

        document = AIContextDocument(
            category=AIContextCategory.STRATEGY,
            title='Distribution thesis',
            slug='distribution-thesis',
            body='Body',
        )

        self.assertEqual(
            str(_document_relative_path(document, date(2026, 6, 3))),
            'docs/strategy/2026/2026-06-03-distribution-thesis.md',
        )


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

    def test_extract_youtube_urls(self):
        from content_ingestion.ai_client import extract_youtube_urls

        urls = extract_youtube_urls(
            'Analiza https://www.youtube.com/watch?v=abc123 y https://youtu.be/xyz789.'
        )
        self.assertEqual(
            urls,
            ['https://www.youtube.com/watch?v=abc123', 'https://youtu.be/xyz789'],
        )

    @override_settings(GEMINI_API_KEY='key', GEMINI_MODEL='gemini-3-flash-preview')
    @patch('content_ingestion.ai_client.requests.post')
    def test_complete_with_youtube_video_sends_file_data(self, post):
        from content_ingestion.ai_client import complete_with_youtube_video

        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': 'analysis'}]}}],
        }

        out = complete_with_youtube_video(
            'Script: hola\nVideo: https://www.youtube.com/watch?v=abc123',
            system='SYS',
        )

        self.assertEqual(out, 'analysis')
        payload = post.call_args.kwargs['json']
        parts = payload['contents'][0]['parts']
        self.assertEqual(parts[0]['file_data']['file_uri'], 'https://www.youtube.com/watch?v=abc123')
        self.assertIn('Script: hola', parts[1]['text'])

    @override_settings(GEMINI_API_KEY='key', GEMINI_MODEL='gemini-3-flash-preview')
    @patch('content_ingestion.ai_client.requests.post')
    def test_complete_with_youtube_video_reports_no_text_reason(self, post):
        from content_ingestion.ai_client import AIClientError, complete_with_youtube_video

        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            'candidates': [{
                'finishReason': 'SAFETY',
                'safetyRatings': [{
                    'category': 'HARM_CATEGORY_DANGEROUS_CONTENT',
                    'probability': 'MEDIUM',
                    'blocked': True,
                }],
            }],
        }

        with self.assertRaises(AIClientError) as ctx:
            complete_with_youtube_video('Video: https://youtu.be/abc123')

        self.assertIn('finishReason: SAFETY', str(ctx.exception))
        self.assertIn('HARM_CATEGORY_DANGEROUS_CONTENT=MEDIUM blocked', str(ctx.exception))

    @override_settings(GEMINI_API_KEY='key', GEMINI_MODEL='gemini-3-flash-preview')
    @patch('content_ingestion.ai_client.requests.post')
    def test_complete_with_images_sends_inline_data(self, post):
        from content_ingestion.ai_client import complete_with_images

        post.return_value.status_code = 200
        post.return_value.json.return_value = {
            'candidates': [{'content': {'parts': [{'text': 'image analysis'}]}}],
        }

        out = complete_with_images('Describe esta imagen', [('image/png', b'abc')], system='SYS')

        self.assertEqual(out, 'image analysis')
        payload = post.call_args.kwargs['json']
        parts = payload['contents'][0]['parts']
        self.assertEqual(parts[0]['inline_data']['mime_type'], 'image/png')
        self.assertEqual(parts[0]['inline_data']['data'], 'YWJj')
        self.assertEqual(parts[1]['text'], 'Describe esta imagen')


class CommandParsingTests(SimpleTestCase):
    def test_split_command(self):
        from content_ingestion.management.commands.telegram_ai_listener import _split_command

        self.assertEqual(_split_command('hello there'), (None, 'hello there'))
        self.assertEqual(_split_command('/claude how are you'), ('/claude', 'how are you'))
        self.assertEqual(_split_command('/debate'), ('/debate', ''))
        self.assertEqual(_split_command('/CLAUDE@SomeBot hi'), ('/claude', 'hi'))

    def test_parse_video_memory_folder_from_slash_title(self):
        from content_ingestion.management.commands.telegram_ai_listener import _parse_memory_tool_args

        parsed = _parse_memory_tool_args(
            'category: videos\n'
            'title: Vida y filosofía / Un influencer coreano con esquizofrenia\n'
            '# Video Memory\n'
            'Body'
        )

        self.assertEqual(parsed['category'], 'videos')
        self.assertEqual(parsed['folder'], 'Vida y filosofía')
        self.assertEqual(parsed['title'], 'Un influencer coreano con esquizofrenia')
        self.assertIn('Body', parsed['body'])

    def test_memory_write_request_detects_doc_revision_with_youtube_link(self):
        from content_ingestion.management.commands.telegram_ai_listener import _is_memory_write_request

        self.assertTrue(_is_memory_write_request(
            'We should revise this existing git docs https://youtu.be/abc123'
        ))
        self.assertFalse(_is_memory_write_request(
            'Can you analyze this YouTube video? https://youtu.be/abc123'
        ))

    def test_sender_authority_hierarchy(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import _sender_authority

        with override_settings(
            CONFIO_AI_TELEGRAM_OWNER_IDENTITIES=['julian', 'j', '123'],
            CONFIO_AI_TELEGRAM_TRUSTED_IDENTITIES=['susy ramirez'],
        ):
            self.assertEqual(_sender_authority(types.SimpleNamespace(first_name='J'), 123), 'owner')
            self.assertEqual(
                _sender_authority(types.SimpleNamespace(first_name='Susy', last_name='Ramirez'), 456),
                'trusted',
            )
            self.assertEqual(_sender_authority(types.SimpleNamespace(first_name='Cliente'), 789), 'client')

    def test_client_authority_does_not_get_write_tools(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import _build_tools

        event = types.SimpleNamespace(chat_id=-100)

        client_tools = _build_tools(None, event, None, authority='client')
        trusted_tools = _build_tools(None, event, None, authority='trusted')

        self.assertNotIn('write_memory', client_tools)
        self.assertNotIn('write_video_memory', client_tools)
        self.assertIn('write_memory', trusted_tools)
        self.assertIn('write_video_memory', trusted_tools)


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

    def test_compose_prompt_includes_authority(self):
        from content_ingestion.management.commands.telegram_ai_listener import _compose_prompt

        owner = _compose_prompt('push it', '', '', sender_name='Julian', authority='owner')
        client = _compose_prompt('push it', '', '', sender_name='Cliente', authority='client')

        self.assertIn('OWNER / Julian', owner)
        self.assertIn('órdenes literales', owner)
        self.assertIn('CLIENT / externo', client)
        self.assertIn('No hagas commit', client)

    def test_media_label_detects_video_and_none(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import _media_label

        video = types.SimpleNamespace(
            media=True, video=True, video_note=None, photo=None, voice=None, audio=None,
            file=types.SimpleNamespace(name='demo.mp4', mime_type='video/mp4'),
        )
        self.assertEqual(_media_label(video), '[video: demo.mp4]')
        self.assertEqual(_media_label(types.SimpleNamespace(media=None)), '')

    def test_image_message_detection(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import (
            _image_mime_type,
            _is_image_message,
        )

        photo = types.SimpleNamespace(media=True, photo=True, file=None)
        doc_image = types.SimpleNamespace(
            media=True,
            photo=None,
            file=types.SimpleNamespace(mime_type='image/png'),
        )
        pdf = types.SimpleNamespace(
            media=True,
            photo=None,
            file=types.SimpleNamespace(mime_type='application/pdf'),
        )

        self.assertTrue(_is_image_message(photo))
        self.assertTrue(_is_image_message(doc_image))
        self.assertFalse(_is_image_message(pdf))
        self.assertEqual(_image_mime_type(photo), 'image/jpeg')
        self.assertEqual(_image_mime_type(doc_image), 'image/png')

    def test_display_name_fallbacks(self):
        import types
        from content_ingestion.management.commands.telegram_ai_listener import _display_name

        self.assertEqual(_display_name(types.SimpleNamespace(first_name='Ana', last_name='Pérez')), 'Ana Pérez')
        self.assertEqual(_display_name(None, 42), 'usuario 42')

    def test_human_size(self):
        from content_ingestion.management.commands.telegram_ai_listener import _human_size

        self.assertEqual(_human_size(0), '')
        self.assertEqual(_human_size(512), '512B')
        self.assertEqual(_human_size(1536), '1.5KB')
        self.assertEqual(_human_size(1024 ** 3), '1.0GB')


class ToolLoopTests(SimpleTestCase):
    def test_parse_tool_call(self):
        from content_ingestion.ai_agent import _parse_tool_call

        tools = {'get_chat_videos': lambda a: '', 'search_knowledge': lambda a: '', 'write_video_memory': lambda a: ''}
        self.assertEqual(_parse_tool_call('TOOL get_chat_videos', tools), ('get_chat_videos', ''))
        self.assertEqual(
            _parse_tool_call('TOOL search_knowledge precios koywe', tools),
            ('search_knowledge', 'precios koywe'),
        )
        self.assertEqual(_parse_tool_call('```\nTOOL get_chat_videos\n```', tools), ('get_chat_videos', ''))
        self.assertEqual(
            _parse_tool_call(
                'TOOL write_video_memory\n'
                'title: Video title\n'
                '# Video title\n\n'
                'Full script here.',
                tools,
            ),
            ('write_video_memory', 'title: Video title\n# Video title\n\nFull script here.'),
        )
        self.assertEqual(
            _parse_tool_call(
                '```\n'
                'TOOL write_video_memory\n'
                'title: Video title\n'
                '# Video title\n'
                '```',
                tools,
            ),
            ('write_video_memory', 'title: Video title\n# Video title'),
        )
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


class MemoryToolTests(SimpleTestCase):
    def test_parse_memory_tool_args(self):
        from content_ingestion.management.commands.telegram_ai_listener import _parse_memory_tool_args

        parsed = _parse_memory_tool_args(
            'category: strategy\n'
            'title: Koywe focus\n'
            '# Koywe focus\n\n'
            'Prioritize Koywe launch.'
        )

        self.assertEqual(parsed['category'], 'strategy')
        self.assertEqual(parsed['title'], 'Koywe focus')
        self.assertIn('Prioritize Koywe', parsed['body'])

    def test_video_memory_title_helpers(self):
        from content_ingestion.management.commands.telegram_ai_listener import (
            _first_title,
            _strip_title_line,
        )

        text = 'title: Coreano camiseta\n# Body\nFull script'
        self.assertEqual(_first_title(text), 'Coreano camiseta')
        self.assertEqual(_strip_title_line(text), '# Body\nFull script')


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


class ConversationLogTests(SimpleTestCase):
    def test_append_writes_turn_and_respects_guard(self):
        import os
        import tempfile
        from datetime import datetime, timezone
        from content_ingestion import conversation_log as cl

        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, '.git'))  # look like a git worktree
            with override_settings(CONFIO_AI_REPO_PATH=d, CONFIO_AI_LOG_CONVERSATIONS=True):
                self.assertTrue(cl.enabled())
                cl.append_turn(-100, 'Ana', 'hola', 'qué tal')
                day = datetime.now(timezone.utc).strftime('%Y-%m-%d')
                path = os.path.join(d, 'docs', 'conversations', '-100', f'{day}.md')
                content = open(path, encoding='utf-8').read()
                self.assertIn('Ana: hola', content)
                self.assertIn('Confío AI: qué tal', content)
            with override_settings(CONFIO_AI_REPO_PATH=d, CONFIO_AI_LOG_CONVERSATIONS=False):
                self.assertFalse(cl.enabled())
            with override_settings(CONFIO_AI_REPO_PATH='/nonexistent', CONFIO_AI_LOG_CONVERSATIONS=True):
                self.assertFalse(cl.enabled())
