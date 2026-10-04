"""Confío IA settings, read lazily so tests can override them."""
from decimal import Decimal

from django.conf import settings

DEFAULTS = {
    'CONFIO_IA_ENABLED': True,
    # Everyday turns (support, navigation, quick questions).
    'CONFIO_IA_MODEL': 'gpt-6-luna',
    'CONFIO_IA_REASONING_EFFORT': 'low',
    # Only the analyze_finances tool reaches the frontier model.
    'CONFIO_IA_ANALYSIS_MODEL': 'gpt-6.1-sol',
    'CONFIO_IA_ANALYSIS_REASONING_EFFORT': 'medium',
    'CONFIO_IA_TRANSCRIBE_MODEL': 'gpt-transcribe',
    'CONFIO_IA_MAX_TOOL_STEPS': 4,
    'CONFIO_IA_HISTORY_MESSAGES': 16,
    'CONFIO_IA_MAX_INPUT_CHARS': 2000,
    'CONFIO_IA_MAX_AUDIO_SECONDS': 120,
    # 2 minutes at the app's 32 kbps plus container overhead: bounds what a
    # forged low-bitrate file can cost even if its headers lie.
    'CONFIO_IA_MAX_AUDIO_BYTES': 640 * 1024,
    # Fair use on the free tier, counted per user per rolling 24h.
    'CONFIO_IA_DAILY_TURNS': 40,
    'CONFIO_IA_DAILY_ANALYSES': 3,
    'CONFIO_IA_HUMAN_MODE_HOURS': 24,
    'CONFIO_IA_REQUEST_TIMEOUT_SECONDS': 25,
    # USD per 1M tokens: (input, cached input, output); transcription per minute.
    'CONFIO_IA_PRICES': {
        'gpt-6-luna': ('0.10', '0.01', '0.50'),
        'gpt-6.1-sol': ('2.00', '0.10', '10.00'),
    },
    'CONFIO_IA_TRANSCRIBE_PRICE_PER_MINUTE': '0.0045',

    # ---- Launch switches (2026-10-04: free launch) ----
    # Confío IA ships free: text, voice notes, analysis, pets. Realtime voice
    # (and the wake word, which opens a call) and IA+ sales stay built but
    # dark: Duende Limited can't be a Google Play merchant (Seychelles), and
    # realtime is the only cost that matters (see confio_ia_economics).
    'CONFIO_IA_REALTIME_ENABLED': False,
    'CONFIO_IA_PLUS_SALES_ENABLED': False,

    # ---- IA+ (US$9.99/month; regional prices are set in each store) ----
    'CONFIO_IA_PLUS_PRODUCT_ID': 'confio_ia_plus_monthly',
    'CONFIO_IA_PLUS_DAILY_TURNS': 300,
    'CONFIO_IA_PLUS_DAILY_ANALYSES': 30,
    'CONFIO_IA_PLUS_VOICE_MINUTES': 100,  # realtime minutes per calendar month
    # Apple: bundle id + numeric App Store id (required to verify production).
    'CONFIO_IA_IOS_BUNDLE_ID': 'com.Confio.Confio',
    # Public (App Store listing id6472662314, iTunes lookup by bundle id).
    'CONFIO_IA_APPLE_APP_ID': 6472662314,
    # Sandbox purchases (TestFlight, App Review) unlock IA+ too: App Review
    # must be able to use what it reviews. They are flagged environment=Sandbox.
    'CONFIO_IA_ACCEPT_APPLE_SANDBOX': True,
    'CONFIO_IA_ANDROID_PACKAGE': 'com.Confio.Confio',
    # Service-account JSON (string or dict) with Play Console financial access.
    'CONFIO_IA_GOOGLE_PLAY_CREDENTIALS': None,
    # Pub/Sub push subscription for RTDN: OIDC audience + the push service account.
    'CONFIO_IA_RTDN_AUDIENCE': None,
    'CONFIO_IA_RTDN_SERVICE_ACCOUNT': None,

    # ---- Realtime voice (IA+) ----
    # mini: ~1/3 of the full model's audio price, so 100 min/month fits US$9.99.
    'CONFIO_IA_REALTIME_MODEL': 'gpt-realtime-2.1-mini',
    'CONFIO_IA_REALTIME_VOICE': 'marin',
    'CONFIO_IA_REALTIME_TRANSCRIBE_MODEL': 'gpt-transcribe',
    # USD per 1M tokens: audio in, audio out, text in, text out, cached in.
    'CONFIO_IA_REALTIME_PRICES': {
        'gpt-realtime-2.1': ('32.00', '64.00', '4.00', '24.00', '0.40'),
        # Text prices for mini are an estimate; the audio side dominates.
        'gpt-realtime-2.1-mini': ('10.00', '20.00', '0.60', '2.40', '0.30'),
    },
    # A call with no heartbeat for this long counts as ended.
    'CONFIO_IA_VOICE_IDLE_SECONDS': 90,

    # ---- User-created pets (gpt-image-2 low ≈ US$0.01 per image) ----
    'CONFIO_IA_PET_IMAGE_MODEL': 'gpt-image-2',
    'CONFIO_IA_PET_IMAGE_QUALITY': 'low',
    # USD per 1M image output tokens, for cost reporting.
    'CONFIO_IA_PET_IMAGE_OUTPUT_PRICE': '40.00',
    'CONFIO_IA_PET_FREE_PER_WEEK': 3,
    'CONFIO_IA_PET_PLUS_PER_DAY': 10,
    'CONFIO_IA_PET_PREFIX': 'confio-ia/pets/',
    'CONFIO_IA_PET_URL_SECONDS': 6 * 3600,

    # ---- "Confío" wake word (IA+, on-device Porcupine) ----
    'CONFIO_IA_PICOVOICE_ACCESS_KEY': None,
}


def get(name):
    return getattr(settings, name, DEFAULTS[name])


def price_for(model):
    prices = get('CONFIO_IA_PRICES') or {}
    entry = prices.get(model)
    if not entry:
        return None
    return tuple(Decimal(str(value)) for value in entry)
