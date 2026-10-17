"""Keeps AppVersionPolicy.latest_version at the version each store serves.

Run hourly by security.sync_store_versions. It only ever raises the policy:
the store is the source of truth for "live", an admin may still set a
higher value by hand, and nothing here lowers it. Any failure logs and
skips that platform; a missed poll only means the prompt comes an hour later.
"""
import logging
import re

import requests
from django.conf import settings
from django.db import transaction

from security.face_client import _version
from security.models import AppVersionPolicy

logger = logging.getLogger(__name__)

IOS_APP_ID = '6472662314'
ANDROID_PACKAGE = 'com.Confio.Confio'
LOOKUP_URL = 'https://itunes.apple.com/lookup'
PLAY_SCOPE = 'https://www.googleapis.com/auth/androidpublisher'
VERSION_IN_NAME = re.compile(r'(?<![0-9.])([0-9]{1,4}\.[0-9]{1,4}\.[0-9]{1,4})(?![0-9.])')


def ios_store_version():
    response = requests.get(LOOKUP_URL, params={'id': IOS_APP_ID}, timeout=10)
    response.raise_for_status()
    results = response.json().get('results') or []
    return results[0].get('version') if results else None


def _play_service():
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    path = getattr(settings, 'GOOGLE_PLAY_SERVICE_ACCOUNT_FILE', None) or \
        str(settings.BASE_DIR / 'config' / 'firebase-service-account.json')
    credentials = service_account.Credentials.from_service_account_file(path, scopes=[PLAY_SCOPE])
    return build('androidpublisher', 'v3', credentials=credentials, cache_discovery=False)


def release_version(release):
    """Play releases carry version codes, not names; the release name is
    Play Console's default "168 (5.2.3)" or a bare "5.2.3". A name with no
    single X.Y.Z in it is skipped rather than guessed."""
    found = set(VERSION_IN_NAME.findall(release.get('name') or ''))
    return found.pop() if len(found) == 1 else None


def android_store_version():
    """Newest fully rolled-out production release. A staged rollout
    ('inProgress') would send most users to a Play page without the update."""
    edits = _play_service().edits()
    edit_id = edits.insert(packageName=ANDROID_PACKAGE, body={}).execute()['id']
    try:
        track = edits.tracks().get(packageName=ANDROID_PACKAGE, editId=edit_id, track='production').execute()
    finally:
        try:
            edits.delete(packageName=ANDROID_PACKAGE, editId=edit_id).execute()
        except Exception:
            logger.warning('Could not delete Play edit %s', edit_id, exc_info=True)
    versions = []
    for release in track.get('releases') or []:
        if release.get('status') != 'completed':
            continue
        version = release_version(release)
        if version is None:
            logger.warning('Play release name %r has no X.Y.Z version; skipped', release.get('name'))
        else:
            versions.append(version)
    return max(versions, key=_version) if versions else None


def raise_latest_version(platform, store_version):
    """Returns True when the policy moved up to store_version."""
    if _version(store_version) is None:
        logger.warning('Store version %r for %s is not X.Y.Z; ignored', store_version, platform)
        return False
    with transaction.atomic():
        policy, _ = AppVersionPolicy.objects.select_for_update().get_or_create(platform=platform)
        current = _version(policy.latest_version)
        if current is not None and current >= _version(store_version):
            return False
        previous = policy.latest_version
        policy.latest_version = store_version
        policy.save(update_fields=['latest_version', 'updated_at'])
    logger.info('AppVersionPolicy %s latest_version %s -> %s (store)', platform, previous or '-', store_version)
    return True


FETCHERS = {'ios': ios_store_version, 'android': android_store_version}


def sync_store_versions():
    changed = {}
    for platform, fetch in FETCHERS.items():
        try:
            store_version = fetch()
            if store_version:
                changed[platform] = raise_latest_version(platform, store_version)
            else:
                logger.warning('No live %s store version found', platform)
        except Exception:
            logger.warning('Could not sync the %s store version', platform, exc_info=True)
    return changed
