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
