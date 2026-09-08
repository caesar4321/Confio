from types import SimpleNamespace
from unittest import mock
import uuid

import graphene
from django.test import SimpleTestCase

from payment_accounts.schema import Mutation, Query


class BridgeSchemaTests(SimpleTestCase):
    def test_recipient_and_owner_cannot_be_supplied_by_client(self):
        schema = graphene.Schema(query=Query, mutation=Mutation)
        fields = schema.graphql_schema.mutation_type.fields['quotePaymentBridge'].args
        self.assertEqual(set(fields), {'fundingInstructionId', 'amount', 'requestId', 'direction'})

    @mock.patch('payment_accounts.schema.quote_provider_funding')
    @mock.patch('payment_accounts.schema._active_account')
    def test_mutation_requires_owner_permission_and_passes_jwt_account(self, active, quote):
        from payment_accounts.schema import QuotePaymentBridge
        account = SimpleNamespace(pk=7)
        active.return_value = account
        quote.return_value = None
        info = SimpleNamespace()
        result = QuotePaymentBridge.mutate(None, info, uuid.uuid4(), '10', uuid.uuid4())
        self.assertTrue(result.success)
        active.assert_called_once_with(info, permission='send_funds', owner_only=True)
        self.assertIs(quote.call_args.kwargs['confio_account'], account)

    def test_every_app_document_matches_the_server_schema(self):
        import re
        from pathlib import Path
        from graphql import parse, validate
        source = Path(__file__).resolve().parents[2] / 'apps/src/services/paymentBridge.ts'
        documents = re.findall(r'gql`([^`]+)`', source.read_text())
        fragment = next(d for d in documents if d.startswith('fragment '))
        schema = graphene.Schema(query=Query, mutation=Mutation).graphql_schema
        for document in documents:
            if document.startswith('fragment '):
                continue
            document = document.replace('${FIELDS}', fragment)
            with self.subTest(document=document.split('{')[0]):
                self.assertEqual(validate(schema, parse(document)), [])

    def test_source_signing_material_is_not_exposed_in_graphql(self):
        schema = graphene.Schema(query=Query, mutation=Mutation).graphql_schema
        fields = schema.type_map['PaymentBridgeTransferType'].fields
        self.assertNotIn('signedRawTx', fields)
        self.assertNotIn('binding', fields)
        self.assertNotIn('sponsorNonce', fields)

    def test_infinia_app_documents_match_schema(self):
        import re
        from pathlib import Path
        from graphql import parse, validate
        source = Path(__file__).resolve().parents[2] / 'apps/src/services/infiniaJourney.ts'
        schema = graphene.Schema(query=Query, mutation=Mutation).graphql_schema
        for document in re.findall(r'gql`([^`]+)`', source.read_text()):
            with self.subTest(document=document.split('{')[0]):
                self.assertEqual(validate(schema, parse(document)), [])

    def test_cobre_app_documents_match_schema(self):
        import re
        from pathlib import Path
        from graphql import parse, validate
        source = Path(__file__).resolve().parents[2] / 'apps/src/services/cobreJourney.ts'
        schema = graphene.Schema(query=Query, mutation=Mutation).graphql_schema
        for document in re.findall(r'gql`([^`]+)`', source.read_text()):
            with self.subTest(document=document.split('{')[0]):
                self.assertEqual(validate(schema, parse(document)), [])
