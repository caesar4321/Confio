"""The QR a person has in front of them, read from a picture of their screen.

Everything embedded is painted over first (cdp.Page.capture): what is inside
a frame belongs to whoever made the frame, not to the store. A QR the size of
a product photo is not the store's payment QR either (runner.py).
"""
import io
import logging
import math

logger = logging.getLogger(__name__)

MASK_MARGIN = 8  # px around an embedded box


def available():
    """Without the decoder no task starts: an order whose code could not be read is never begun."""
    try:
        import zxingcpp
        return bool(zxingcpp.read_barcodes)
    except ImportError:
        logger.warning('the QR decoder is not installed')
        return False


def masked(picture):
    from PIL import Image, ImageDraw
    image = Image.open(io.BytesIO(picture.png)).convert('RGB')
    paint = ImageDraw.Draw(image)
    for x0, y0, x1, y1 in picture.boxes:
        left = max(0, int(x0 * picture.scale) - MASK_MARGIN)
        top = max(0, int(y0 * picture.scale) - MASK_MARGIN)
        right = min(image.width, int(x1 * picture.scale) + MASK_MARGIN)
        bottom = min(image.height, int(y1 * picture.scale) + MASK_MARGIN)
        if right > left and bottom > top:
            paint.rectangle((left, top, right, bottom), fill=(127, 127, 127))
    return image


def read(picture):
    """[(text, side)] for every QR in the picture, the embedded ones painted
    over; side is its edge as the page lays it out, in CSS px."""
    import zxingcpp
    found = zxingcpp.read_barcodes(masked(picture), formats=zxingcpp.BarcodeFormat.QRCode)
    out = []
    for item in found:
        if not item.valid or not item.text:
            continue
        p = item.position
        corners = [(c.x, c.y) for c in (p.top_left, p.top_right, p.bottom_right, p.bottom_left)]
        edge = max(math.dist(corners[i], corners[(i + 1) % 4]) for i in range(4))
        out.append((item.text.strip(), edge / (picture.scale * picture.zoom)))
    return out


def texts(picture):
    return {text for text, _ in read(picture)}
