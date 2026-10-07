"""Pure aggregation helpers for rail-interest demand probes."""


def build_rail_interest_metrics(rows):
    """Aggregate demand probes by distinct person rather than event count.

    Authenticated users are the canonical identity. A non-empty session ID is
    the fallback for pre-authenticated probes; rows with neither identity are
    excluded because they cannot be counted per person reliably.
    """
    rail_totals = {}
    all_tapped = set()
    all_confirmed = set()
    unidentified_events = 0

    for row in rows:
        user_id = row.get('user_id')
        session_id = str(row.get('session_id') or '').strip()
        if user_id is not None:
            identity = ('user', user_id)
        elif session_id:
            identity = ('session', session_id)
        else:
            unidentified_events += 1
            continue

        props = row.get('properties') or {}
        rail = str(props.get('rail') or '—')
        direction = str(
            props.get('direction')
            or ('receive' if row.get('event_name') == 'receive_rail_interest' else '—')
        )
        key = (rail, direction)
        bucket = rail_totals.setdefault(key, {
            'rail': rail,
            'direction': direction,
            '_tapped': set(),
            '_confirmed': set(),
            'countries': set(),
            'last_seen': None,
        })

        stage = str(props.get('stage') or 'tap')
        # A confirmation can only happen after the alert opened from a tap.
        # Treat it as evidence of both stages even if the fire-and-forget tap
        # event was lost, keeping the user conversion bounded at 100%.
        bucket['_tapped'].add(identity)
        all_tapped.add(identity)
        if stage == 'confirmed':
            bucket['_confirmed'].add(identity)
            all_confirmed.add(identity)

        if row.get('country'):
            bucket['countries'].add(row['country'])
        created_at = row.get('created_at')
        if created_at is not None and (
            bucket['last_seen'] is None or created_at > bucket['last_seen']
        ):
            bucket['last_seen'] = created_at

    rail_interest = []
    for bucket in rail_totals.values():
        taps = len(bucket.pop('_tapped'))
        confirmed = len(bucket.pop('_confirmed'))
        rail_interest.append({
            **bucket,
            'taps': taps,
            'confirmed': confirmed,
            'countries': ', '.join(sorted(bucket['countries'])) or '—',
            'conversion_pct': round(confirmed / taps * 100, 1) if taps else 0.0,
        })

    rail_interest.sort(key=lambda item: (-item['confirmed'], -item['taps']))
    totals = {
        'taps': len(all_tapped),
        'confirmed': len(all_confirmed),
        'rails': len(rail_interest),
        'unidentified_events': unidentified_events,
    }
    return rail_interest, totals


def merge_waitlist_counts(rail_interest, waitlist_by_rail):
    """Attach the all-time waitlist size to each 90-day rail row.

    `waitlist_by_rail` maps rail_id → {'count', 'direction', 'kind'}. Rails
    with no 90-day probe row still have people waiting — taps that aged out,
    or nationality-blocked rails, whose events this panel does not read — so
    they get a row of their own instead of vanishing.
    """
    remaining = dict(waitlist_by_rail)
    rows = []
    for row in rail_interest:
        entry = remaining.pop(row['rail'], None) or {}
        rows.append({**row, 'waitlist': entry.get('count', 0), 'waitlist_kind': entry.get('kind', '')})
    for rail_id, entry in sorted(remaining.items(), key=lambda kv: (-kv[1]['count'], kv[0])):
        rows.append({
            'rail': rail_id,
            'direction': entry.get('direction') or '—',
            'taps': 0,
            'confirmed': 0,
            'conversion_pct': 0.0,
            'countries': '—',
            'last_seen': None,
            'waitlist': entry['count'],
            'waitlist_kind': entry.get('kind', ''),
        })
    return rows
