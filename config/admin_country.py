"""A "Country" column and filter on every admin list that shows a person.

The country is User.country: where the person lives (90-day IP residence,
users/residence.py), the one the app and the rails use since phone-less
signup. ConfioAdminSite.register calls add_country_column for each admin, so
apps registering later get it too.
"""
from django.contrib import admin

# Rows about someone other than their direct user link (a release names the
# staff member who sent it; the person is the volunteer).
PATH_OVERRIDES = {
    'humanitarian.humanitarianrelease': 'volunteer_application__user',
}
# Staff or actor links: never "who the row is about".
ACTOR_FIELDS = {
    'released_by', 'reviewed_by', 'approved_by', 'hired_by', 'deactivated_by', 'resolved_by',
    'assigned_to', 'processed_by', 'verified_by', 'invited_by', 'cancelled_by', 'decided_by',
    'added_by', 'uploaded_by', 'updated_by', 'modified_by', 'last_modified_by',
}

# Which user a row is "about", most specific first.
USER_FIELD_PREFERENCE = (
    'user', 'sender_user', 'payer_user', 'inviter_user', 'donor_user', 'owner', 'buyer_user',
    'recipient_user', 'claimed_by', 'created_by', 'requested_by', 'author', 'member',
)


def country_flag(code: str) -> str:
    code = (code or '').upper()
    if len(code) != 2 or not code.isalpha():
        return ''
    return ''.join(chr(0x1F1E6 + ord(ch) - ord('A')) for ch in code)


def _user_field(model):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    user_fks = {
        field.name for field in model._meta.get_fields()
        if (getattr(field, 'many_to_one', False) or getattr(field, 'one_to_one', False))
        and getattr(field, 'related_model', None) is User
        and not field.auto_created and field.name not in ACTOR_FIELDS
    }
    for name in USER_FIELD_PREFERENCE:
        if name in user_fks:
            return name
    return sorted(user_fks)[0] if user_fks else None


def _forward_relations(model):
    return [f for f in model._meta.get_fields()
            if f.is_relation and not f.auto_created and (f.many_to_one or f.one_to_one) and f.concrete]


def _non_null_paths(model, prefix='', depth=5, seen=None):
    """The joins Django's select_related() would make: non-null FKs, nested."""
    seen = set() if seen is None else seen
    paths = []
    if depth == 0:
        return paths
    for field in _forward_relations(model):
        if field.null:
            continue
        name = f'{prefix}{field.name}'
        key = (model, field.name)
        if key in seen:
            continue
        paths.append(name)
        paths += _non_null_paths(field.related_model, f'{name}__', depth - 1, seen | {key})
    return paths


def _path_is_non_null(model, path):
    current = model
    for part in path.split('__'):
        field = next((f for f in _forward_relations(current) if f.name == part), None)
        if field is None or field.null:
            return False
        current = field.related_model
    return True


def add_country_column(model, model_admin):
    from django.contrib.auth import get_user_model
    User = get_user_model()
    if model is User:
        path = None
    else:
        path = PATH_OVERRIDES.get(model._meta.label_lower) or _user_field(model)
        if path is None:
            return
    display = list(model_admin.list_display or ())
    shown = {name for name in display if isinstance(name, str)}
    if (display == ['__str__'] or hasattr(model_admin, 'user_country')
            or shown & {'country', 'user_country', 'country_display'}
            or any(name.endswith('__country') for name in shown)):
        # Lists that already show the residence country, or their own country
        # column, keep theirs. A phone_country column still gets this one.
        return

    def user_country(obj):
        person = obj
        for part in ([] if path is None else path.split('__')):
            person = getattr(person, part, None) if person is not None else None
        code = (getattr(person, 'country', '') or '').upper()
        return f'{country_flag(code)} {code}'.strip() if code else '—'

    user_country.short_description = 'Country'
    user_country.admin_order_field = 'country' if path is None else f'{path}__country'
    # A bound method name the changelist can find on the ModelAdmin.
    setattr(model_admin, 'user_country', user_country)
    # After the first column (the row's name/link), so it is seen at once.
    model_admin.list_display = tuple(display[:1] + ['user_country'] + display[1:])

    if path is not None:
        # One join, not one query per row (nullable FKs are not preloaded),
        # added to what the admin already preloads rather than replacing it
        # (a select_related on get_queryset makes the changelist skip
        # list_select_related).
        current = model_admin.list_select_related
        if current is False:
            # Django joins automatically only when list_display shows a
            # relation, and then follows every non-null FK, nested.
            shows_relation = any(
                isinstance(name, str) and any(f.name == name for f in _forward_relations(model))
                for name in display)
            if not shows_relation:
                model_admin.list_select_related = (path,)
            elif not _path_is_non_null(model, path):
                # Spell out what the automatic join loaded, plus the user.
                model_admin.list_select_related = tuple(dict.fromkeys(_non_null_paths(model) + [path]))
        elif isinstance(current, (list, tuple)):
            model_admin.list_select_related = tuple(dict.fromkeys(list(current) + [path]))

    lookup = 'country' if path is None else f'{path}__country'
    filters = list(model_admin.list_filter or ())
    if lookup not in filters and 'country' not in filters:
        model_admin.list_filter = tuple(filters + [(lookup, admin.AllValuesFieldListFilter)])
