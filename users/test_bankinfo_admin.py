from types import SimpleNamespace
from unittest.mock import patch

from django.contrib import admin
from django.db.models.sql.compiler import SQLCompiler
from django.test import SimpleTestCase, override_settings
from django.urls import path

from users.admin import AccountAdmin, BankInfoAdmin
from users.models import Account, BankInfo


urlpatterns = [path('admin/', admin.site.urls)]


@override_settings(ROOT_URLCONF=__name__)
class BankInfoAdminPerformanceTests(SimpleTestCase):
    def test_empty_owner_and_verifier_widgets_do_not_query_the_database(self):
        model_admin = BankInfoAdmin(BankInfo, admin.site)
        request = SimpleNamespace(user=SimpleNamespace(has_perm=lambda perm: True))
        for name in ('account', 'verified_by'):
            with self.subTest(field=name):
                field = model_admin.formfield_for_foreignkey(
                    BankInfo._meta.get_field(name), request)
                # SimpleTestCase forbids DB queries. A normal select enumerates
                # every related row here, even when there is no selection.
                html = field.widget.render(name, None)
                self.assertIn('admin-autocomplete', html)
                self.assertIn('data-ajax--url=', html)

    def test_existing_selection_only_queries_selected_id(self):
        model_admin = BankInfoAdmin(BankInfo, admin.site)
        for name in ('account', 'verified_by'):
            with self.subTest(field=name):
                queries = []

                def capture_query(compiler, *args, **kwargs):
                    queries.append(compiler.as_sql())
                    return iter(())

                field = model_admin.formfield_for_foreignkey(
                    BankInfo._meta.get_field(name), SimpleNamespace())
                # Capture actual compiled SQL without requiring customer data.
                with patch.object(SQLCompiler, 'execute_sql', capture_query):
                    field.widget.render(name, 373)
                self.assertEqual(len(queries), 1)
                sql, params = queries[0]
                self.assertIn('"id" IN (%s)', sql)
                self.assertEqual(params, (373,))

    def test_autocomplete_relations_have_registered_search_admins(self):
        model_admin = BankInfoAdmin(BankInfo, admin.site)
        self.assertEqual(
            model_admin.checks_class()._check_autocomplete_fields(model_admin), [])

    def test_account_search_loads_label_relations_in_same_query(self):
        queryset = AccountAdmin(Account, admin.site).get_queryset(SimpleNamespace())
        sql = str(queryset.query)
        self.assertIn('JOIN "users_user"', sql)
        self.assertIn('JOIN "users_business"', sql)
