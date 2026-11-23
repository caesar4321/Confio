"""A very small Chrome DevTools client: just what one task step needs.

One connection per step, closed at its end, so no worker holds a browser
while a model thinks for long or a person types a password.
"""
import base64
import json
import logging
import time
from dataclasses import dataclass

from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

MAX_MESSAGE_BYTES = 32 * 1024 * 1024
MAX_NODES = 80_000  # an order page has a few thousand
MAX_TEXT_NODES = 20_000
_NOT_TEXT = frozenset({'SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'TITLE', 'HEAD'})
OPEN_SECONDS = 15
CALL_SECONDS = 20
# websockets logs the handshake's path at DEBUG, and that path carries the signing key.
_QUIET = logging.getLogger('agent_tasks.cdp.socket')
_QUIET.setLevel(logging.CRITICAL)
_QUIET.propagate = False


class CdpError(Exception):
    pass


EMBEDS = frozenset({'IFRAME', 'FRAME', 'EMBED', 'OBJECT', 'FENCEDFRAME', 'PORTAL', 'WEBVIEW'})


@dataclass(frozen=True)
class Picture:
    url: str
    png: bytes
    boxes: tuple  # every embedded thing on it, as on screen, in CSS px
    scale: float  # device px per CSS px
    zoom: float = 1.0  # the person's pinch zoom
    words: tuple = ()  # the page's own text, field values and copy-button data (no embedded document)
    fields: tuple = ()  # copy-button text and read-only boxes only: what product data is not echoed into
    text: tuple = ()  # the page's text nodes in reading order, without scripts and styles (SPEI details)


def newest(targets):
    """The tab a store's last click left in front. Listing order alone is not
    enough (vendors differ), so a tab another one opened wins; between equals,
    the last listed, which is the newest on Browserbase."""
    openers = {target.get('openerId') for target in targets}
    opened = [t for t in targets if t.get('openerId') and t['targetId'] not in openers]
    return (opened or targets)[-1]


class Page:
    """One connection to a browser, for one step.

    active   while the agent works: the browser is kept to one tab, dialogs
             are answered no, and every document request can be checked.
    passive  once the person has the checkout: nothing is closed, answered or
             intercepted, and no script runs in any page. Only `capture`: a
             picture of the one tab the person was shown, as they see it.
    """

    def __init__(self, connect_url, *, active=True):
        self._url, self._socket, self._session, self._next = connect_url, None, None, 0
        self._active, self._allowed, self._main = active, None, ''
        self._pages, self._page_session = [], None
        self._sending = None
        self.target = ''
        self.refused_send = False
        self.refused_document = False
        self._loading = False  # a document was let through and has not arrived

    def __enter__(self):
        try:
            self._socket = connect(self._url, max_size=MAX_MESSAGE_BYTES, open_timeout=OPEN_SECONDS,
                                   logger=_QUIET)
            targets = [t for t in self.call('Target.getTargets')['targetInfos']
                       if t.get('type') == 'page' and not str(t.get('url', '')).startswith('devtools://')]
            if not targets:
                raise CdpError('browser has no page')
            if not self._active:
                self._pages = targets
                return self
            kept = newest(targets)
            for target in targets:
                if target['targetId'] != kept['targetId']:
                    self.call('Target.closeTarget', {'targetId': target['targetId']})
            self._attach(kept['targetId'])
            self.target = str(kept['targetId'])
            self._page_session = self._session
            try:
                # One left open by the last step blocks everything until it is answered.
                self.call('Page.handleJavaScriptDialog', {'accept': False}, seconds=5)
            except CdpError:
                pass  # none was open
            try:
                self.call('Page.enable', seconds=5)
            except CdpError:
                # A dialog that opened while nobody listened holds the page and
                # cannot be answered. Loading the same address lets go of it.
                # Not its own address: asking for that again could repeat an act.
                self.call('Page.navigate', {'url': 'about:blank'})
                self.call('Page.enable')
        except CdpError:
            self.close()
            raise
        except Exception as exc:
            self.close()
            # The URL carries the signing key: only the exception's type is kept.
            raise CdpError(f'could not attach to the browser: {type(exc).__name__}') from None
        return self

    def _attach(self, target):
        self._session = self.call('Target.attachToTarget', {'targetId': target, 'flatten': True})['sessionId']

    def guard_documents(self, allowed):
        """`allowed(url, method)` decides each document the tab asks for,
        redirects included, until this connection closes."""
        self._main = self.call('Page.getFrameTree')['frameTree']['frame']['id']
        self._allowed = allowed
        self.call('Network.enable')
        # A service worker answers before the interception would see the request.
        self.call('Network.setBypassServiceWorker', {'bypass': True})
        self.call('Fetch.enable', {'patterns': [{'urlPattern': '*', 'resourceType': 'Document',
                                                 'requestStage': 'Request'}]})

    def only_sending(self, allowed):
        """While one act is sent, every request is checked, not only
        documents: `allowed(method, url)`. None goes back to documents."""
        self._sending = allowed
        everything = [{'urlPattern': '*', 'requestStage': 'Request'}]
        documents = [{'urlPattern': '*', 'resourceType': 'Document', 'requestStage': 'Request'}]
        self.call('Fetch.enable', {'patterns': documents if allowed is None else everything})

    def _tell(self, method, params):
        self._next += 1
        message = {'id': self._next, 'method': method, 'params': params}
        # The page's own session, also while a browser-wide call is in flight.
        if self._page_session or self._session:
            message['sessionId'] = self._page_session or self._session
        self._socket.send(json.dumps(message))

    def _on_event(self, event):
        params = event.get('params') or {}
        if not self._active:
            return
        if event.get('method') == 'Page.javascriptDialogOpening':
            # Never accepted: "confirm the purchase?" is answered no. Only "leave
            # this page?" is yes, or a page could keep the agent from going back.
            self._tell('Page.handleJavaScriptDialog', {'accept': params.get('type') == 'beforeunload'})
        elif event.get('method') == 'Fetch.requestPaused':
            request = params.get('request') or {}
            url, method = str(request.get('url') or ''), str(request.get('method') or '')
            document = params.get('resourceType', 'Document') == 'Document' and params.get('frameId') == self._main
            try:
                fine = ((self._sending is None or self._sending(method, url))
                        and (self._allowed is None or not document or self._allowed(url, method)))
            except Exception:  # noqa: BLE001 - unreadable is refused
                fine = False
            if fine:
                if document:
                    self._loading = True
                self._tell('Fetch.continueRequest', {'requestId': params.get('requestId')})
            else:
                if self._sending is not None and not document:
                    self.refused_send = True
                if document:
                    self.refused_document = True
                    self._loading = False
                self._tell('Fetch.failRequest', {'requestId': params.get('requestId'), 'errorReason': 'Aborted'})
        elif event.get('method') == 'Page.frameNavigated':
            if (params.get('frame') or {}).get('id') == self._main:
                self._loading = False

    def pump(self, seconds):
        """Wait, answering what the browser asks meanwhile. A plain sleep
        would leave a redirect unanswered, and closing lets it through."""
        deadline = time.monotonic() + seconds
        while True:
            left = deadline - time.monotonic()
            if left <= 0:
                return
            try:
                event = json.loads(self._socket.recv(timeout=left))
            except TimeoutError:
                return
            except (OSError, ValueError, WebSocketException) as exc:
                raise CdpError(f'browser connection: {type(exc).__name__}') from None
            if event.get('method'):
                self._on_event(event)

    def __exit__(self, *exc):
        if self._socket is not None and self._allowed is not None:
            try:
                # Closing lets go of whatever is paused: answer it first.
                self.pump(0.4)
                if self._loading:
                    self.call('Page.stopLoading', seconds=5)
            except CdpError:
                pass
        self.close()

    def _browser_call(self, method, params=None):
        session, self._session = self._session, None
        try:
            return self.call(method, params, seconds=10)
        finally:
            self._session = session

    # ------------------------------------------------- what the person sees

    def _embedded(self, view):
        """Where each embedded thing is on screen, whoever made it, inside
        shadow roots too. One that takes no room has no box. `view` places
        the page's boxes on the screen when the person has zoomed in."""
        tree = self.call('DOM.getDocument', {'depth': -1, 'pierce': True}, seconds=10)['root']
        found, waiting, words, fields, text = [], [(tree, False)], [], [], []
        while waiting:
            node, unread = waiting.pop()
            if node.get('nodeName') in EMBEDS:
                found.append(node['backendNodeId'])
                continue  # covered whole, whatever is inside
            if node.get('nodeType') == 3 and node.get('nodeValue'):
                words.append(node['nodeValue'])
                if not unread and node['nodeValue'].strip():
                    text.append(node['nodeValue'].strip())
            attributes = node.get('attributes') or []
            named = dict(zip(attributes[::2], attributes[1::2]))
            for name, value in named.items():
                if name in ('value', 'data-clipboard-text', 'data-copy', 'data-code') and value:
                    words.append(value)
            # A copy field is what a store writes for copying: a copy button's
            # text, or a read-only box. Not an option, a hidden input or a
            # data-code, which echo product data (SKUs, variations, names).
            kind = node.get('nodeName')
            read_only = 'readonly' in named
            if named.get('data-clipboard-text'):
                fields.append(named['data-clipboard-text'])
            if kind == 'INPUT' and read_only and named.get('type', 'text').lower() == 'text' and named.get('value'):
                fields.append(named['value'])
            if kind == 'TEXTAREA' and read_only:
                fields.extend(child['nodeValue'] for child in node.get('children') or []
                              if child.get('nodeType') == 3 and child.get('nodeValue'))
            # Reading order: a stack pops last first. A shadow root draws in its host's place.
            unread = unread or kind in _NOT_TEXT
            waiting.extend((child, unread) for child in reversed(node.get('children') or []))
            waiting.extend((child, unread) for child in reversed(node.get('shadowRoots') or []))
        # Text too long to read whole is not read at all (None): never half a page.
        self._words, self._fields = tuple(words), tuple(fields)
        self._text = tuple(text) if len(text) <= MAX_TEXT_NODES else None
        boxes = []
        for node in found:
            try:
                quad = self.call('DOM.getBoxModel', {'backendNodeId': node}, seconds=5)['model']['border']
            except CdpError as exc:
                if 'compute box model' in str(exc):
                    continue
                raise
            zoom, left, top = view
            box = tuple(value for value in (
                (min(quad[::2]) - left) * zoom, (min(quad[1::2]) - top) * zoom,
                (max(quad[::2]) - left) * zoom, (max(quad[1::2]) - top) * zoom))
            if box[2] - box[0] >= 4 and box[3] - box[1] >= 4:  # nothing smaller holds a QR
                boxes.append(box)
        return set(boxes)

    def capture(self, target):
        """Two pictures of that tab as it is on screen, or None when it is
        gone or it moved meanwhile. No script runs in it and it gets no focus."""
        if not any(page.get('targetId') == target for page in self._pages):
            return None
        self._attach(target)

        def address():
            frame = self.call('Page.getFrameTree', seconds=8)['frameTree']['frame']
            return str(frame.get('url') or ''), str(frame.get('urlFragment') or '')

        where = address()
        # The whole tree is read four times: a page far larger than any order
        # page would cost a worker its memory. Counted without running a script.
        self.call('Performance.enable', seconds=8)
        # Removed nodes count until they are collected: a long single-page session is not a large page.
        self.call('HeapProfiler.collectGarbage', seconds=15)
        counted = {item.get('name'): item.get('value') for item in
                   self.call('Performance.getMetrics', seconds=8).get('metrics') or []}
        if float(counted.get('Nodes') or 0) > MAX_NODES:
            return None
        metrics = self.call('Page.getLayoutMetrics', seconds=8)
        visual = metrics['cssVisualViewport']
        view = (float(visual.get('scale') or 1), float(visual.get('offsetX') or 0), float(visual.get('offsetY') or 0))
        css, device = metrics['cssLayoutViewport']['clientWidth'], metrics['layoutViewport']['clientWidth']
        scale = max(float(device) / float(css), 1.0) if css else 1.0
        shots = []
        for _ in range(2):
            # What was embedded just before or just after each picture is
            # painted over: a frame that moves in between is covered both places.
            before = self._embedded(view)
            data = self.call('Page.captureScreenshot', {'format': 'png', 'captureBeyondViewport': False},
                             seconds=15)['data']
            if address() != where:
                return None
            boxes = tuple(sorted(before | self._embedded(view)))
            shots.append(Picture(url=''.join(where), png=base64.b64decode(data), boxes=boxes, scale=scale,
                                 zoom=view[0], words=self._words, fields=self._fields,
                                 text=self._text))
        return tuple(shots)

    def close(self):
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:  # noqa: BLE001 - already gone
                pass
            self._socket = None

    def call(self, method, params=None, *, seconds=CALL_SECONDS):
        if self._socket is None:
            raise CdpError('not connected')
        self._next += 1
        wanted, message = self._next, {'id': self._next, 'method': method, 'params': params or {}}
        if self._session:
            message['sessionId'] = self._session
        deadline = time.monotonic() + seconds
        try:
            self._socket.send(json.dumps(message))
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise CdpError(f'{method} took too long')
                answer = json.loads(self._socket.recv(timeout=left))
                if answer.get('method'):
                    self._on_event(answer)
                    continue
                if answer.get('id') != wanted:
                    continue  # an event
                if 'error' in answer:
                    raise CdpError(f"{method}: {str(answer['error'].get('message'))[:120]}")
                return answer.get('result') or {}
        except CdpError:
            raise
        except (TimeoutError, OSError, ValueError, WebSocketException) as exc:
            raise CdpError(f'{method}: {type(exc).__name__}') from None

    def click(self, x, y):
        """A real click at a point of the page, as a finger's: the page's own scripts answer it."""
        for kind, button, count in (('mouseMoved', 'none', 0), ('mousePressed', 'left', 1),
                                    ('mouseReleased', 'left', 1)):
            self.call('Input.dispatchMouseEvent', {'type': kind, 'x': x, 'y': y, 'button': button,
                                                   'clickCount': count})

    def insert(self, text):
        """Type into whatever has the focus. Never logged: it may be a password."""
        self.call('Input.insertText', {'text': text})

    def enter(self):
        for kind in ('keyDown', 'keyUp'):
            self.call('Input.dispatchKeyEvent', {
                'type': kind, 'key': 'Enter', 'code': 'Enter', 'windowsVirtualKeyCode': 13,
                'nativeVirtualKeyCode': 13, **({'text': '\r'} if kind == 'keyDown' else {})})

    def evaluate(self, expression):
        out = self.call('Runtime.evaluate', {'expression': expression, 'returnByValue': True, 'awaitPromise': True})
        if out.get('exceptionDetails'):
            raise CdpError('page script failed')
        return (out.get('result') or {}).get('value')

    def goto(self, url):
        out = self.call('Page.navigate', {'url': url})
        if out.get('errorText') and not self.refused_document:
            raise CdpError(f"navigation failed: {str(out['errorText'])[:80]}")
        self.settle()

    def settle(self, seconds=8.0):
        """Wait for the document, then a moment for what it renders."""
        deadline = time.monotonic() + seconds
        self.pump(0.8)
        while time.monotonic() < deadline:
            try:
                if not self._loading and self.evaluate('document.readyState') == 'complete':
                    break
            except CdpError:
                pass  # between two documents
            self.pump(0.5)
        self.pump(1.2)
        if self._loading:
            # Its next redirect would come when nobody is left to check it.
            self.call('Page.stopLoading')
            self._loading = False
