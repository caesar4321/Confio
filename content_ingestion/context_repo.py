from __future__ import annotations

import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from .models import AIContextCommitStatus, AIContextDocument


class ContextRepoError(Exception):
    pass


def _repo_root() -> Path:
    repo_path = Path(settings.CONFIO_AI_REPO_PATH).expanduser().resolve()
    if not repo_path.exists():
        raise ContextRepoError(f'ConfioAI repo path does not exist: {repo_path}')
    if not (repo_path / '.git').exists():
        raise ContextRepoError(f'ConfioAI repo path is not a git worktree: {repo_path}')
    return repo_path


def _context_root(repo_root: Path) -> Path:
    root = (repo_root / settings.CONFIO_AI_CONTEXT_ROOT).resolve()
    if repo_root not in root.parents and root != repo_root:
        raise ContextRepoError('CONFIO_AI_CONTEXT_ROOT must stay inside CONFIO_AI_REPO_PATH')
    return root


def _safe_slug(title: str) -> str:
    value = slugify(title)[:100].strip('-')
    return value or 'untitled'


def _frontmatter_value(value):
    if value is None:
        return ''
    text = str(value).replace('"', '\\"')
    return f'"{text}"'


def render_markdown(document: AIContextDocument) -> str:
    metadata = document.metadata or {}
    lines = [
        '---',
        f'title: {_frontmatter_value(document.title)}',
        f'category: {_frontmatter_value(document.category)}',
        f'created_at: {_frontmatter_value(document.created_at.isoformat() if document.created_at else timezone.now().isoformat())}',
    ]
    for key in sorted(metadata):
        if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_-]*$', str(key)):
            continue
        value = metadata[key]
        if isinstance(value, (str, int, float, bool)) or value is None:
            lines.append(f'{key}: {_frontmatter_value(value)}')
    lines.extend(['---', '', document.body.strip(), ''])
    return '\n'.join(lines)


def _run_git(repo_root: Path, *args: str) -> str:
    result = subprocess.run(
        ['git', *args],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or '').strip()
        raise ContextRepoError(output or f'git {" ".join(args)} failed')
    return result.stdout.strip()


def _has_changes(repo_root: Path, relative_path: str) -> bool:
    result = subprocess.run(
        ['git', 'status', '--porcelain', '--', relative_path],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or '').strip()
        raise ContextRepoError(output or 'git status failed')
    return bool(result.stdout.strip())


def write_commit_and_push_context(document: AIContextDocument, *, push: bool = True) -> AIContextDocument:
    repo_root = _repo_root()
    root = _context_root(repo_root)
    date = timezone.localdate()
    slug = document.slug or _safe_slug(document.title)
    document.slug = slug

    relative_path = Path(settings.CONFIO_AI_CONTEXT_ROOT) / document.category / str(date.year) / f'{date.isoformat()}-{slug}.md'
    target = (repo_root / relative_path).resolve()
    if repo_root not in target.parents:
        raise ContextRepoError('Resolved context path escapes CONFIO_AI_REPO_PATH')

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render_markdown(document), encoding='utf-8')
    document.relative_path = str(relative_path)
    document.save(update_fields=['slug', 'relative_path', 'updated_at'])

    if not _has_changes(repo_root, document.relative_path):
        return document

    _run_git(repo_root, 'add', document.relative_path)
    _run_git(repo_root, 'commit', '-m', f'Add AI context: {document.title}')
    sha = _run_git(repo_root, 'rev-parse', 'HEAD')
    document.commit_sha = sha
    document.committed_at = timezone.now()
    document.status = AIContextCommitStatus.COMMITTED
    document.error = ''
    document.save(update_fields=['commit_sha', 'committed_at', 'status', 'error', 'updated_at'])

    if push:
        remote = getattr(settings, 'CONFIO_AI_REPO_REMOTE', 'origin')
        branch = getattr(settings, 'CONFIO_AI_REPO_BRANCH', 'main')
        _run_git(repo_root, 'push', remote, branch)
        document.status = AIContextCommitStatus.PUSHED
        document.pushed_at = timezone.now()
        document.save(update_fields=['status', 'pushed_at', 'updated_at'])

    return document

