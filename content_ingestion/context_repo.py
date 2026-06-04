from __future__ import annotations

import fcntl
import re
import subprocess
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from django.utils.text import slugify

from .models import AIContextCommitStatus, AIContextDocument


class ContextRepoError(Exception):
    pass


# Shared with conversation_log.py and confioai-pull.service.
GIT_LOCKFILE = '/tmp/confioai-git.lock'


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


def _safe_folder(folder: str) -> Path | None:
    parts = []
    for raw in str(folder or '').replace('\\', '/').split('/'):
        part = raw.strip().strip('.')
        if part:
            parts.append(part[:80])
    return Path(*parts) if parts else None


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


def _has_any_changes(repo_root: Path, relative_paths: list[str]) -> bool:
    result = subprocess.run(
        ['git', 'status', '--porcelain', '--', *relative_paths],
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output = (result.stderr or result.stdout or '').strip()
        raise ContextRepoError(output or 'git status failed')
    return bool(result.stdout.strip())


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


def _safe_context_relative_path(path: str) -> Path:
    clean = str(path or '').strip().replace('\\', '/').lstrip('/')
    if not clean:
        raise ContextRepoError('Falta path del documento.')
    relative = Path(clean)
    if any(part in {'', '.', '..'} for part in relative.parts):
        raise ContextRepoError(f'Path inválido: {path}')
    root = Path(settings.CONFIO_AI_CONTEXT_ROOT)
    if relative.parts[: len(root.parts)] != root.parts:
        relative = root / relative
    if relative.suffix.lower() != '.md':
        raise ContextRepoError(f'Solo se pueden editar archivos Markdown: {relative}')
    return relative


def _substantial_shrink(existing: str, replacement: str) -> bool:
    existing_len = len((existing or '').strip())
    replacement_len = len((replacement or '').strip())
    if existing_len < 1200:
        return False
    return replacement_len < max(700, int(existing_len * 0.65))


def _document_title_from_markdown(text: str, fallback: str) -> str:
    in_frontmatter = False
    for idx, line in enumerate((text or '').splitlines()[:80]):
        stripped = line.strip()
        if idx == 0 and stripped == '---':
            in_frontmatter = True
            continue
        if in_frontmatter and stripped == '---':
            in_frontmatter = False
            continue
        if in_frontmatter:
            key, sep, value = stripped.partition(':')
            if sep and key.strip().lower() == 'title':
                title = value.strip().strip('"').strip("'").replace('\\"', '"')
                return title or fallback
        if stripped.startswith('# '):
            return stripped[2:].strip() or fallback
    return fallback


def list_memory_documents(category: str = '', max_rows: int = 200) -> str:
    repo_root = _repo_root()
    root = _context_root(repo_root)
    if not root.exists():
        return f'No encontré {settings.CONFIO_AI_CONTEXT_ROOT} en ConfioAI.'

    category = (category or '').strip().strip('/').replace('\\', '/')
    scan_root = (root / category).resolve() if category else root
    if root not in scan_root.parents and scan_root != root:
        raise ContextRepoError('La categoría solicitada escapa CONFIO_AI_CONTEXT_ROOT')
    if not scan_root.exists():
        return f'No encontré docs/{category} en ConfioAI.' if category else 'No encontré documentos en ConfioAI.'

    rows = []
    for path in sorted(scan_root.rglob('*.md')):
        if path.name == '.gitkeep':
            continue
        if 'conversations' in path.relative_to(root).parts:
            continue
        relative = path.relative_to(repo_root)
        try:
            text = path.read_text(encoding='utf-8')
        except OSError:
            continue
        fallback = path.stem.replace('-', ' ').title()
        title = _document_title_from_markdown(text, fallback)
        doc_category = path.relative_to(root).parts[0] if path.relative_to(root).parts else ''
        rows.append((doc_category, title, str(relative)))

    if not rows:
        return f'No hay memorias registradas en docs/{category}.' if category else 'No hay memorias registradas en ConfioAI.'

    shown = rows[:max_rows]
    label = f'docs/{category}' if category else 'ConfioAI docs'
    lines = [f'Total documentos en {label}: {len(rows)}']
    for idx, (doc_category, title, relative) in enumerate(shown, 1):
        prefix = f'[{doc_category}] ' if not category and doc_category else ''
        lines.append(f'{idx}. {prefix}{title} — {relative}')
    if len(rows) > len(shown):
        lines.append(f'... {len(rows) - len(shown)} más no mostrados.')
    return '\n'.join(lines)


def list_video_memories() -> str:
    return list_memory_documents('videos').replace('Total documentos en docs/videos:', 'Total videos:')


def read_context_documents(paths: list[str]) -> str:
    repo_root = _repo_root()
    out = []
    for raw_path in paths:
        relative = _safe_context_relative_path(raw_path)
        target = (repo_root / relative).resolve()
        if repo_root not in target.parents:
            raise ContextRepoError('Resolved context path escapes CONFIO_AI_REPO_PATH')
        if not target.exists():
            out.append(f'FILE: {relative}\n(MISSING)')
            continue
        out.append(f'FILE: {relative}\n<<<\n{target.read_text(encoding="utf-8")}\n>>>')
    return '\n\n'.join(out)


def revise_context_documents(edits: list[dict], *, message: str = '', push: bool = True) -> dict:
    if not edits:
        raise ContextRepoError('No hay documentos para revisar.')

    lock_fd = open(GIT_LOCKFILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return _revise_context_documents_locked(edits, message=message, push=push)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()


def _revise_context_documents_locked(edits: list[dict], *, message: str = '', push: bool = True) -> dict:
    repo_root = _repo_root()
    _context_root(repo_root)
    remote = getattr(settings, 'CONFIO_AI_REPO_REMOTE', 'origin')
    branch = getattr(settings, 'CONFIO_AI_REPO_BRANCH', 'main')

    _run_git(repo_root, 'pull', '--rebase', '--autostash', remote, branch)

    changed_paths = []
    for edit in edits:
        relative = _safe_context_relative_path(edit.get('path', ''))
        target = (repo_root / relative).resolve()
        if repo_root not in target.parents:
            raise ContextRepoError('Resolved context path escapes CONFIO_AI_REPO_PATH')

        action = str(edit.get('action') or 'write').lower()
        if action == 'delete':
            if target.exists():
                target.unlink()
                changed_paths.append(str(relative))
            continue

        body = str(edit.get('body') or '').strip()
        if not body:
            raise ContextRepoError(f'Falta markdown para {relative}')
        if target.exists() and not edit.get('allow_shrink'):
            existing = target.read_text(encoding='utf-8')
            if _substantial_shrink(existing, body):
                raise ContextRepoError(
                    f'La revisión de {relative} es mucho más corta que el archivo actual. '
                    'Probablemente borraría scripts, métricas o detalles previos. '
                    'Lee el documento actual y envía una versión fusionada completa; '
                    'usa allow_shrink: yes solo si Julian pidió explícitamente simplificar.'
                )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body.rstrip() + '\n', encoding='utf-8')
        changed_paths.append(str(relative))

    if not changed_paths or not _has_any_changes(repo_root, changed_paths):
        return {'status': 'NO_CHANGES', 'paths': changed_paths, 'commit': ''}

    _run_git(repo_root, 'add', *changed_paths)
    commit_message = (message or 'Revise AI context docs').strip()[:180]
    _run_git(repo_root, 'commit', '-m', commit_message)
    sha = _run_git(repo_root, 'rev-parse', 'HEAD')
    if push:
        _push_with_rebase_retry(repo_root, remote, branch)
    return {'status': 'PUSHED' if push else 'COMMITTED', 'paths': changed_paths, 'commit': sha}


def _document_relative_path(document: AIContextDocument, date) -> Path:
    slug = document.slug or _safe_slug(document.title)
    base = Path(settings.CONFIO_AI_CONTEXT_ROOT) / document.category
    if document.category == 'videos':
        folder = _safe_folder((document.metadata or {}).get('folder', ''))
        if folder:
            return base / folder / f'{slug}.md'
        return base / f'{slug}.md'
    filename = f'{date.isoformat()}-{slug}.md'
    return base / str(date.year) / filename


def write_commit_and_push_context(document: AIContextDocument, *, push: bool = True) -> AIContextDocument:
    lock_fd = open(GIT_LOCKFILE, 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        return _write_commit_and_push_context_locked(document, push=push)
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
        except OSError:
            pass
        lock_fd.close()


def _write_commit_and_push_context_locked(document: AIContextDocument, *, push: bool = True) -> AIContextDocument:
    repo_root = _repo_root()
    root = _context_root(repo_root)
    remote = getattr(settings, 'CONFIO_AI_REPO_REMOTE', 'origin')
    branch = getattr(settings, 'CONFIO_AI_REPO_BRANCH', 'main')

    _run_git(repo_root, 'pull', '--rebase', '--autostash', remote, branch)

    date = timezone.localdate()
    slug = document.slug or _safe_slug(document.title)
    document.slug = slug

    relative_path = _document_relative_path(document, date)
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
        _push_with_rebase_retry(repo_root, remote, branch)
        document.status = AIContextCommitStatus.PUSHED
        document.pushed_at = timezone.now()
        document.save(update_fields=['status', 'pushed_at', 'updated_at'])

    return document


def _push_with_rebase_retry(repo_root: Path, remote: str, branch: str) -> None:
    try:
        _run_git(repo_root, 'push', remote, branch)
    except ContextRepoError:
        _run_git(repo_root, 'pull', '--rebase', '--autostash', remote, branch)
        _run_git(repo_root, 'push', remote, branch)
