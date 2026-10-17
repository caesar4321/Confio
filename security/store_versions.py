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


def _play_credentials():
    from google.oauth2 import service_account
    path = getattr(settings, 'GOOGLE_PLAY_SERVICE_ACCOUNT_FILE', None) or \
        str(settings.BASE_DIR / 'config' / 'firebase-service-account.json')
    return service_account.Credentials.from_service_account_file(path, scopes=[PLAY_SCOPE])


def _play_service():
    from googleapiclient.discovery import build
    return build('androidpublisher', 'v3', credentials=_play_credentials(), cache_discovery=False)


PUBLISHED = 'RELEASE_LIFECYCLE_STATE_PUBLISHED'
RELEASES_URL = ('https://androidpublisher.googleapis.com/androidpublisher/v3/'
                f'applications/{ANDROID_PACKAGE}/tracks/production/releases')


def published_releases():
    """[(name, version codes)] of production releases Play has PUBLISHED.

    Only tracks.releases.list carries the review state. The edits track says
    'completed' the moment a full rollout is SUBMITTED, so with managed
    publishing off a release still in review read as live there (5.2.5,
    2026-10-17), and the live release it supersedes drops off it. The bundled
    API client predates releases.list, so it is called directly."""
    from google.auth.transport.requests import AuthorizedSession
    response = AuthorizedSession(_play_credentials()).get(RELEASES_URL, timeout=15)
    response.raise_for_status()
    return [
        (release.get('releaseName') or '',
         {str(a.get('versionCode')) for a in release.get('activeArtifacts') or []})
        for release in response.json().get('releases') or []
        if release.get('releaseLifecycleState') == PUBLISHED
    ]


def full_rollout_version_codes():
    """Version codes the edits production track holds at 100% ('completed').

    'completed' alone is not live: with managed publishing off a full rollout
    reads 'completed' the moment it is SUBMITTED. And 'PUBLISHED' alone is not
    everyone: Play counts staged and halted rollouts as published. Only a
    release that is both is served to every user."""
    edits = _play_service().edits()
    edit_id = edits.insert(packageName=ANDROID_PACKAGE, body={}).execute()['id']
    try:
        track = edits.tracks().get(packageName=ANDROID_PACKAGE, editId=edit_id, track='production').execute()
    finally:
        try:
            edits.delete(packageName=ANDROID_PACKAGE, editId=edit_id).execute()
        except Exception:
            logger.warning('Could not delete Play edit %s', edit_id, exc_info=True)
    return {str(code) for release in track.get('releases') or []
            if release.get('status') == 'completed'
            for code in release.get('versionCodes') or []}


def release_version(name):
    """Play releases carry version codes, not names; the release name is
    Play Console's default "168 (5.2.3)" or a bare "5.2.3". A name with no
    single X.Y.Z in it is skipped rather than guessed."""
    found = set(VERSION_IN_NAME.findall(name or ''))
    return found.pop() if len(found) == 1 else None


def android_store_version():
    """Newest production release Play serves to everyone: published (not in
    review) AND at 100% on the track (not staged or halted). While a newer
    release is in review the live one drops off the track, so this returns
    nothing and latest_version simply stays where it was (never lowered)."""
    published = published_releases()
    full_rollout = full_rollout_version_codes()
    versions = []
    for name, codes in published:
        if not codes or not codes <= full_rollout:
            continue
        version = release_version(name)
        if version is None:
            logger.warning('Play release name %r has no X.Y.Z version; skipped', name)
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
