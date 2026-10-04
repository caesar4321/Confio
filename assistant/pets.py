"""User-created pets for Confio Assistant (like OpenAI's dots or Meta's Muse):
describe an idea, or start from a photo of your own pet, and get a character
drawn in Confío's style. Private to the user; limited per week (free) or per
day (Assistant+). One image per creation (~US$0.01); moods are animated in the app.
"""
from __future__ import annotations

import base64
import binascii
import json
import logging
from datetime import timedelta
from decimal import Decimal

import requests
from django.conf import settings
from django.utils import timezone

from . import billing, conf
from .models import AssistantProfile, CustomPet, Mascot

logger = logging.getLogger(__name__)

STYLE = (
    'Personaje mascota para una app, tierno y amigable, cuerpo redondeado, ilustración plana suave '
    'con sombreado ligero, colores cálidos, de frente, cuerpo completo y centrado con margen, '
    'fondo blanco liso, sin texto, sin letras, sin logos, sin marcas, sin personas.'
)
PHOTO_STYLE = (
    'Convierte al animal de la foto en un personaje mascota tierno y redondeado, manteniendo sus '
    'rasgos (color del pelaje, manchas, orejas). ' + STYLE
)
MAX_PHOTO_BYTES = 4 * 1024 * 1024
PHOTO_TYPES = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/webp': 'webp'}


class PetError(Exception):
    """Shown to the user (Spanish). Infrastructure failures refund the slot."""


class PetRejected(PetError):
    """The idea/photo was refused after paid checks: the attempt counts."""


def _headers():
    key = getattr(settings, 'OPENAI_API_KEY', '')
    if not key:
        raise PetError('Personalizar a tu asistente no está disponible ahora.')
    return {'Authorization': f'Bearer {key}'}


def creations_left(user):
    now = timezone.now()
    recent = CustomPet.objects.filter(user=user)
    if billing.has_plus(user):
        used = recent.filter(created_at__gte=now - timedelta(days=1)).count()
        return max(conf.get('CONFIO_ASSISTANT_PET_PLUS_PER_DAY') - used, 0), 'day'
    used = recent.filter(created_at__gte=now - timedelta(days=7)).count()
    return max(conf.get('CONFIO_ASSISTANT_PET_FREE_PER_WEEK') - used, 0), 'week'


def _moderate(text=None, image_data_url=None):
    inputs = []
    if text:
        inputs.append({'type': 'text', 'text': text})
    if image_data_url:
        inputs.append({'type': 'image_url', 'image_url': {'url': image_data_url}})
    if not inputs:
        return
    try:
        r = requests.post('https://api.openai.com/v1/moderations', headers=_headers(),
                          json={'model': 'omni-moderation-latest', 'input': inputs}, timeout=20)
        r.raise_for_status()
    except requests.RequestException as exc:
        # Fail closed: an unchecked prompt is not drawn.
        raise PetError('No pudimos revisar tu idea ahora. Inténtalo en un momento.') from exc
    results = r.json().get('results')
    # A missing or malformed verdict is "unknown", never "clean".
    if (not isinstance(results, list) or len(results) == 0
            or any(not isinstance(x, dict) or not isinstance(x.get('flagged'), bool) for x in results)):
        raise PetError('No pudimos revisar tu idea ahora. Inténtalo en un momento.')
    if any(x['flagged'] for x in results):
        raise PetRejected('Esa idea no se puede usar. Prueba con otra.')


def _photo_is_a_pet(data_url):
    """Refuse photos of people: a pet must never become someone's likeness."""
    payload = {
        'model': conf.get('CONFIO_ASSISTANT_MODEL'),
        'input': [{'role': 'user', 'content': [
            {'type': 'input_text', 'text': (
                'Responde solo JSON {"persona": bool, "animal_o_objeto": bool}. '
                'persona = aparece una persona real (cara o cuerpo). '
                'animal_o_objeto = aparece un animal, peluche o dibujo.')},
            {'type': 'input_image', 'image_url': data_url},
        ]}],
        'text': {'format': {'type': 'json_object'}},
        'max_output_tokens': 200,
        'store': False,
    }
    try:
        r = requests.post('https://api.openai.com/v1/responses', headers={**_headers(), 'Content-Type': 'application/json'},
                          json=payload, timeout=30)
        r.raise_for_status()
        data = r.json()
        text = data.get('output_text') or ''.join(
            part.get('text', '') for item in data.get('output', []) if item.get('type') == 'message'
            for part in item.get('content', []))
        verdict = json.loads(text or '{}')
    except (requests.RequestException, ValueError) as exc:
        raise PetError('No pudimos revisar la foto ahora. Inténtalo en un momento.') from exc
    person, animal = verdict.get('persona'), verdict.get('animal_o_objeto')
    if not isinstance(person, bool) or not isinstance(animal, bool):
        raise PetError('No pudimos revisar la foto ahora. Inténtalo en un momento.')
    if person:
        raise PetRejected('Usa una foto de tu mascota, sin personas.')
    if not animal:
        raise PetRejected('No vimos un animal en la foto. Prueba con otra.')


def create_pet(user, *, idea='', photo_base64=None, photo_mime=None):
    from django.db import transaction

    from .service import lock_user
    # One creation at a time per user, so parallel requests can't all see the
    # same remaining allowance.
    with transaction.atomic():
        lock_user(user)
        left, period = creations_left(user)
        if left <= 0:
            raise PetError('Ya creaste tus personajes de esta semana.' if period == 'week'
                           else 'Ya creaste tus personajes de hoy. Mañana puedes crear más.')
        # Holds the slot (counted by creations_left) while the image is drawn.
        slot = CustomPet.objects.create(user=user, source='photo' if photo_base64 else 'idea', image_key='',
                                        model=conf.get('CONFIO_ASSISTANT_PET_IMAGE_MODEL'))
    try:
        return _create_pet(user, slot, idea=idea, photo_base64=photo_base64, photo_mime=photo_mime)
    except PetRejected:
        # Refused after paid checks: the attempt counts (hidden from the list),
        # so a rejected photo can't be retried for free forever.
        slot.deleted_at = timezone.now()
        slot.save(update_fields=['deleted_at'])
        raise
    except Exception:
        # Our failure (outage, upload): give the slot back.
        slot.delete()
        raise


def _create_pet(user, slot, *, idea='', photo_base64=None, photo_mime=None):
    idea = ' '.join((idea or '').split())[:300]
    model = conf.get('CONFIO_ASSISTANT_PET_IMAGE_MODEL')
    quality = conf.get('CONFIO_ASSISTANT_PET_IMAGE_QUALITY')

    if photo_base64:
        extension = PHOTO_TYPES.get((photo_mime or '').lower())
        if extension is None:
            raise PetError('Usa una foto JPG, PNG o WEBP.')
        try:
            photo = base64.b64decode(photo_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise PetError('No pudimos leer la foto.') from exc
        if not photo or len(photo) > MAX_PHOTO_BYTES:
            raise PetError('La foto es demasiado grande.')
        data_url = f'data:{photo_mime};base64,{photo_base64}'
        _moderate(text=idea or None, image_data_url=data_url)
        _photo_is_a_pet(data_url)
        prompt = PHOTO_STYLE + (f' Detalle extra del usuario: {idea}' if idea else '')
        try:
            response = requests.post(
                'https://api.openai.com/v1/images/edits', headers=_headers(),
                files={'image[]': (f'mascota.{extension}', photo, photo_mime)},
                data={'model': model, 'prompt': prompt, 'size': '1024x1024', 'quality': quality,
                      'output_format': 'png'},
                timeout=120,
            )
        except requests.RequestException as exc:
            raise PetError('No pudimos crear tu asistente ahora.') from exc
        source = 'photo'
    else:
        if len(idea) < 3:
            raise PetError('Cuéntanos cómo quieres a tu asistente.')
        _moderate(text=idea)
        try:
            response = requests.post(
                'https://api.openai.com/v1/images/generations',
                headers={**_headers(), 'Content-Type': 'application/json'},
                json={'model': model, 'prompt': f'{STYLE} Idea del usuario: {idea}', 'size': '1024x1024',
                      'quality': quality, 'output_format': 'png', 'n': 1},
                timeout=120,
            )
        except requests.RequestException as exc:
            raise PetError('No pudimos crear tu asistente ahora.') from exc
        source = 'idea'

    if response.status_code >= 400:
        logger.warning('Pet image failed: %s %s', response.status_code, response.text[:300])
        if 'moderation' in response.text or 'safety' in response.text:
            raise PetRejected('Esa idea no se puede usar. Prueba con otra.')
        raise PetError('No pudimos crear tu asistente ahora.')
    data = response.json()
    image = base64.b64decode(data['data'][0]['b64_json'])
    tokens = int(((data.get('usage') or {}).get('output_tokens')) or 0)
    cost = Decimal(tokens) * Decimal(str(conf.get('CONFIO_ASSISTANT_PET_IMAGE_OUTPUT_PRICE'))) / Decimal(1_000_000)

    from security.s3_utils import build_s3_key, upload_object
    key = build_s3_key(conf.get('CONFIO_ASSISTANT_PET_PREFIX') + str(user.id), 'pet.png')
    upload_object(key=key, body=image, content_type='image/png')
    slot.source, slot.idea, slot.image_key, slot.model, slot.cost_usd = source, idea, key, model, cost
    slot.save(update_fields=['source', 'idea', 'image_key', 'model', 'cost_usd'])
    return slot


def pet_url(pet):
    if pet is None or pet.deleted_at:
        return None
    from security.s3_utils import generate_presigned_get
    try:
        return generate_presigned_get(key=pet.image_key, expires_in_seconds=conf.get('CONFIO_ASSISTANT_PET_URL_SECONDS'))
    except Exception:  # noqa: BLE001 - a missing image falls back to Confi
        logger.exception('Pet URL failed for %s', pet.id)
        return None


def use_pet(user, pet_id):
    profile, _ = AssistantProfile.objects.get_or_create(user=user)
    if pet_id is None:
        profile.custom_pet = None
        if profile.mascot == Mascot.CUSTOM:
            profile.mascot = Mascot.CONFI
    else:
        pet = CustomPet.objects.filter(id=pet_id, user=user, deleted_at__isnull=True).exclude(image_key='').first()
        if pet is None:
            raise PetError('Ese personaje ya no existe.')
        profile.custom_pet = pet
        profile.mascot = Mascot.CUSTOM
    profile.save(update_fields=['custom_pet', 'mascot', 'updated_at'])
    return profile


def delete_pet(user, pet_id):
    pet = CustomPet.objects.filter(id=pet_id, user=user, deleted_at__isnull=True).first()
    if pet is None:
        return
    pet.deleted_at = timezone.now()
    pet.save(update_fields=['deleted_at'])
    AssistantProfile.objects.filter(user=user, custom_pet=pet).update(custom_pet=None, mascot=Mascot.CONFI)
