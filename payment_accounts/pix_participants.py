"""Which payment institution hosts a Pix charge, from public data only.

A payer that is a Pix participant checks a dynamic charge's site against the
Central Bank's registry of QR-site certificates (CERTQRC). That registry is
served only on the participants' private network, so it is out of reach here.

What is public, and what this module joins (BCB "Manual de Segurança do SFN,
Vol. II", section 5.1, and the public list of Pix participants):

  - a QR site must present an EV certificate, without wildcards; an EV
    certificate's subject carries the legal entity's CNPJ (serialNumber);
  - the Central Bank publishes every Pix participant with its ISPB and CNPJ.

So: the site's own TLS certificate (already validated for the host by the
fetch) names a company; if that company is a Pix participant, the charge is
hosted by that institution. Sites whose certificate does not carry a Brazilian
CNPJ (a foreign parent company) or that are hosted by a sponsor can be listed
by hand (PixChargeHost), reviewed by staff.

This says who HOSTS and signs the charge. It never says who the receiver is:
that is the DICT name, which only a participant can read. A site we cannot
tie to a participant is not fraud, only unverified: the card says so.
"""
import csv
import io
import logging
import re
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

EV_POLICY = '2.23.140.1.1'  # CA/Browser Forum: extended validation
LIST_URL = ('https://www.bcb.gov.br/content/estabilidadefinanceira/participantes_pix/'
            'lista-participantes-instituicoes-em-adesao-pix-{date:%Y%m%d}.csv')
MAX_LIST_BYTES = 4 * 1024 * 1024
STALE_AFTER = timedelta(days=30)


def _digits(value):
    return re.sub(r'\D', '', str(value or ''))


def site_identity(der):
    """What the site's TLS certificate says about its owner: organization,
    CNPJ (14 digits or ''), whether it is EV and whether it uses a wildcard.
    None for a certificate that cannot be read."""
    if not der:
        return None
    try:
        from cryptography import x509
        from cryptography.x509.oid import ExtensionOID, NameOID
        certificate = x509.load_der_x509_certificate(der)

        def first(oid):
            values = certificate.subject.get_attributes_for_oid(oid)
            return str(values[0].value) if values else ''
        try:
            policies = certificate.extensions.get_extension_for_oid(ExtensionOID.CERTIFICATE_POLICIES).value
            ev = any(policy.policy_identifier.dotted_string == EV_POLICY for policy in policies)
        except x509.ExtensionNotFound:
            ev = False
        try:
            names = certificate.extensions.get_extension_for_oid(
                ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value.get_values_for_type(x509.DNSName)
        except x509.ExtensionNotFound:
            names = []
        cnpj = _digits(first(NameOID.SERIAL_NUMBER))
        # A CNPJ only for a company registered in Brazil: another country's
        # registration number that happens to have 14 digits is not one.
        brazilian = first(NameOID.COUNTRY_NAME).upper() == 'BR'
        return {'organization': ' '.join(first(NameOID.ORGANIZATION_NAME).split())[:140],
                'cnpj': cnpj if len(cnpj) == 14 and brazilian else '', 'ev': bool(ev),
                'wildcard': any(str(name).startswith('*') for name in names) or first(NameOID.COMMON_NAME).startswith('*')}
    except Exception:  # noqa: BLE001 - an unreadable certificate vouches for nothing
        logger.warning('Pix site certificate could not be read', exc_info=True)
        return None


def list_is_current():
    from .models import PixParticipant
    latest = PixParticipant.objects.order_by('-updated_at').values_list('updated_at', flat=True).first()
    return latest is not None and timezone.now() - latest < STALE_AFTER


def institution_for(host, site):
    """{'name', 'ispb', 'source'} of the Pix participant that hosts charges on
    `host`, or None. A hand-reviewed host wins; otherwise the site's EV
    certificate must name a company on a current participants list."""
    from .models import PixChargeHost, PixParticipant
    host = str(host or '').lower().strip('.')
    if not host:
        return None
    listed = PixChargeHost.objects.filter(host=host, active=True).select_related('participant').first()
    if listed is not None:
        if listed.participant_id and not listed.participant.active:
            return None  # the institution it was reviewed for has left Pix
        name = listed.participant.name if listed.participant_id else listed.institution_name
        if name:
            return {'name': name, 'ispb': listed.participant.ispb if listed.participant_id else '',
                    'source': 'reviewed_host'}
    if not site or not site.get('ev') or site.get('wildcard') or not site.get('cnpj'):
        return None
    if not list_is_current():
        # An old list may name an institution that has since left Pix.
        return None
    # The legal entity is the CNPJ's first eight digits (the rest numbers its
    # branches): a certificate issued to any branch names the same company.
    matches = list(PixParticipant.objects.filter(cnpj__startswith=site['cnpj'][:8], active=True)[:2])
    if len(matches) != 1:
        return None
    participant = matches[0]
    return {'name': participant.name, 'ispb': participant.ispb, 'source': 'ev_certificate'}


# ------------------------------------------------------------ the public list

def parse_list(text):
    """Rows of the Central Bank's participants CSV: [{'name', 'ispb', 'cnpj',
    'kind', 'participation'}]. Tolerant of the separator and of preamble
    lines; a row without an 8-digit ISPB and a 14-digit CNPJ is skipped."""
    lines = text.splitlines()
    start = next((i for i, line in enumerate(lines) if 'ISPB' in line.upper() and 'CNPJ' in line.upper()), None)
    if start is None:
        raise ValueError('participants list has no header')
    delimiter = ';' if lines[start].count(';') >= lines[start].count(',') else ','
    # The file goes on, after a blank line, with the institutions still in the
    # process of joining: they are not participants and are never read.
    end = next((i for i in range(start + 1, len(lines))
                if not lines[i].strip(delimiter + ' \t') or delimiter not in lines[i]), len(lines))
    reader = csv.reader(io.StringIO('\n'.join(lines[start:end])), delimiter=delimiter)
    header = [' '.join(cell.split()).upper() for cell in next(reader)]

    def column(*needles):
        return next((i for i, cell in enumerate(header) if all(n in cell for n in needles)), None)
    name, ispb, cnpj = column('NOME'), column('ISPB'), column('CNPJ')
    kind, participation = column('TIPO', 'INSTITUI'), column('MODALIDADE')
    if None in (name, ispb, cnpj):
        raise ValueError('participants list is missing a column')
    rows = {}
    for cells in reader:
        if len(cells) <= max(name, ispb, cnpj):
            continue
        number, company = _digits(cells[ispb]), _digits(cells[cnpj])
        if not number:
            continue  # a row with no ISPB is not a participant (it must never read as ISPB 00000000)
        number = number.zfill(8)
        # A CNPJ printed without its leading zeros (Banco do Brasil's is
        # 00.000.000/0001-91) is padded back to 14 digits.
        company = company.zfill(14) if 1 <= len(company) <= 14 else ''
        if len(number) != 8 or not company or not cells[name].strip():
            continue
        rows[number] = {
            'name': ' '.join(cells[name].split())[:140], 'ispb': number, 'cnpj': company,
            'kind': ' '.join(cells[kind].split())[:80] if kind is not None and len(cells) > kind else '',
            'participation': (' '.join(cells[participation].split())[:80]
                              if participation is not None and len(cells) > participation else '')}
    return list(rows.values())


def fetch_list(today=None, *, days_back=10):
    """The newest published list (the file name carries its date). Returns
    (date, text) or raises."""
    import requests
    today = today or timezone.localdate()
    for back in range(days_back + 1):
        day = today - timedelta(days=back)
        response = requests.get(LIST_URL.format(date=day), timeout=20, stream=True,
                                headers={'User-Agent': 'Confio-Pix/1.0'})
        if response.status_code != 200:
            continue
        body = response.raw.read(MAX_LIST_BYTES + 1, decode_content=True)
        if len(body) > MAX_LIST_BYTES:
            raise ValueError('participants list is too large')
        for encoding in ('utf-8-sig', 'latin-1'):
            try:
                return day, body.decode(encoding)
            except UnicodeDecodeError:
                continue
    raise ValueError('no participants list published in the last days')


def refresh(text=None, *, listed_on=None):
    """Replace the stored participants with the published list. Refuses a
    list that is implausibly short (a truncated or changed file must not
    silently drop every institution). Returns the number of participants."""
    from django.db import transaction
    from .models import PixParticipant
    if text is None:
        listed_on, text = fetch_list()
    rows = parse_list(text)
    minimum = int(getattr(settings, 'PIX_PARTICIPANTS_MIN_ROWS', 300))
    if len(rows) < minimum:
        raise ValueError(f'participants list has only {len(rows)} rows')
    listed_on = listed_on or timezone.localdate()
    now = timezone.now()
    with transaction.atomic():
        seen = set()
        for row in rows:
            PixParticipant.objects.update_or_create(ispb=row['ispb'], defaults={
                'name': row['name'], 'cnpj': row['cnpj'], 'kind': row['kind'],
                'participation': row['participation'], 'listed_on': listed_on, 'active': True, 'updated_at': now})
            seen.add(row['ispb'])
        PixParticipant.objects.exclude(ispb__in=seen).update(active=False, updated_at=now)
    return len(rows)
