from types import SimpleNamespace
from unittest.mock import Mock

from django.contrib.admin import AdminSite
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase

from billing.admin import (
    BillingObligationAdmin, BillingPaymentAdmin, BillingScheduleAdmin,
    CipSandboxApplicationReceiptAdmin, InstitutionApplicationAdmin,
    ObligationSubjectAdmin,
)
from billing.models import (
    BillingObligation, BillingPayment, BillingSchedule,
    CipSandboxApplicationReceipt, InstitutionApplication, ObligationSubject,
)


class BillingAdminIntegrityTests(SimpleTestCase):
    def test_operator_cannot_edit_or_delete_financial_evidence(self):
        request = SimpleNamespace(user=Mock(is_superuser=True))
        for model, admin_class in (
                (BillingObligation, BillingObligationAdmin),
                (BillingPayment, BillingPaymentAdmin),
                (BillingSchedule, BillingScheduleAdmin),
                (ObligationSubject, ObligationSubjectAdmin),
                (InstitutionApplication, InstitutionApplicationAdmin),
                (CipSandboxApplicationReceipt, CipSandboxApplicationReceiptAdmin)):
            model_admin = admin_class(model, AdminSite())
            self.assertEqual(set(model_admin.get_readonly_fields(request)),
                             {field.name for field in model._meta.fields})
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_view_only_operator_cannot_invoke_retry_actions(self):
        request = SimpleNamespace(user=Mock(has_perm=Mock(return_value=False)))
        model_admin = InstitutionApplicationAdmin(InstitutionApplication, AdminSite())
        for action in (model_admin.apply_selected_now, model_admin.queue_selected_for_retry):
            with self.assertRaises(PermissionDenied):
                action(request, Mock())
