"""GraphQL for Confío IA's memory. Its own documents, all named *AssistantMemory*:
an older server rejects only these. The scope is the JWT's account context; no
argument names a user, an account or a business."""
import graphene
from django.utils.crypto import constant_time_compare, salted_hmac
from graphql_jwt.decorators import login_required

from inbox.schema import get_context_models

from . import memory, memory_rules

NOT_AVAILABLE = 'La memoria todavía no está disponible para ti.'
NOT_FOUND = 'Eso ya no está en tu memoria.'
OTHER_ACCOUNT = 'Cambiaste de cuenta. Abre Memoria de nuevo.'


class AssistantMemoryFactType(graphene.ObjectType):
    id = graphene.ID(required=True)
    text = graphene.String(required=True)


class AssistantMemoryQuoteType(graphene.ObjectType):
    id = graphene.ID(required=True)
    text = graphene.String(required=True, description="The person's own words, digits masked")
    said_at = graphene.DateTime(required=True)


def opened_for(scope):
    """Which memory a screen was showing. It never chooses one (the JWT does): a
    change sent from a screen of another account is refused."""
    return salted_hmac('assistant.memory.screen',
                       f'{scope.user_id}:{scope.account_id}:{scope.business_id}').hexdigest()[:20]


class AssistantMemoryType(graphene.ObjectType):
    opened_for = graphene.String(required=True, description='Send back with a change: refused if the account changed')
    available = graphene.Boolean(required=True)
    can_remember = graphene.Boolean(required=True)
    can_recall = graphene.Boolean(required=True)
    facts_enabled = graphene.Boolean(required=True)
    recall_enabled = graphene.Boolean(required=True)
    facts = graphene.List(graphene.NonNull(AssistantMemoryFactType), required=True)
    quotes = graphene.List(graphene.NonNull(AssistantMemoryQuoteType), required=True)


def _scope(info):
    user, account, business, _ = get_context_models(info)
    return memory.Scope.from_context(user, account, business)


def payload(scope):
    row = scope.row()
    can_remember, can_recall = memory.facts_allowed(scope.user_id), memory.summary_allowed(scope.user_id)
    # Shown whatever the switches say: what is stored can always be seen and deleted.
    facts = [(f.pk, memory_rules.label(f.kind, f.value)) for f in memory.live_facts(row)]
    quotes = memory.summary_messages(scope, row)
    return AssistantMemoryType(
        opened_for=opened_for(scope),
        available=bool(can_remember or can_recall or facts or quotes),
        can_remember=can_remember, can_recall=can_recall,
        facts_enabled=memory.facts_enabled(row), recall_enabled=memory.recall_enabled(row),
        facts=[AssistantMemoryFactType(id=str(pk), text=text) for pk, text in facts if text],
        quotes=[AssistantMemoryQuoteType(id=str(m.id), text=memory_rules.quote(m.body), said_at=m.created_at)
                for m in quotes])


class Query(graphene.ObjectType):
    assistant_memory = graphene.Field(AssistantMemoryType, required=True)

    @login_required
    def resolve_assistant_memory(self, info):
        return payload(_scope(info))


def _same_account(scope, sent):
    return constant_time_compare(str(sent or ''), opened_for(scope))


class SetAssistantMemory(graphene.Mutation):
    class Arguments:
        opened_for = graphene.String(required=True)
        facts_enabled = graphene.Boolean()
        recall_enabled = graphene.Boolean()

    success = graphene.Boolean(required=True)
    error = graphene.String()
    memory = graphene.Field(AssistantMemoryType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, opened_for, facts_enabled=None, recall_enabled=None):
        scope = _scope(info)
        if not _same_account(scope, opened_for):
            return cls(success=False, error=OTHER_ACCOUNT, memory=payload(scope))
        done = memory.set_switches(scope, facts=facts_enabled, recall=recall_enabled)
        return cls(success=done, error=None if done else NOT_AVAILABLE, memory=payload(scope))


class ForgetAssistantMemory(graphene.Mutation):
    class Arguments:
        fact_id = graphene.ID()
        quote_id = graphene.ID()

    success = graphene.Boolean(required=True)
    error = graphene.String()
    memory = graphene.Field(AssistantMemoryType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, fact_id=None, quote_id=None):
        scope = _scope(info)
        try:
            if fact_id and not quote_id:
                done = memory.forget_fact(scope, int(fact_id))
            elif quote_id and not fact_id:
                done = memory.forget_quote(scope, int(quote_id))
            else:
                done = False
        except (TypeError, ValueError):
            done = False
        return cls(success=done, error=None if done else NOT_FOUND, memory=payload(scope))


class WipeAssistantMemory(graphene.Mutation):
    class Arguments:
        opened_for = graphene.String(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    memory = graphene.Field(AssistantMemoryType, required=True)

    @classmethod
    @login_required
    def mutate(cls, root, info, opened_for):
        scope = _scope(info)
        if not _same_account(scope, opened_for):
            return cls(success=False, error=OTHER_ACCOUNT, memory=payload(scope))
        memory.wipe(scope)
        return cls(success=True, memory=payload(scope))


class Mutation(graphene.ObjectType):
    set_assistant_memory = SetAssistantMemory.Field()
    forget_assistant_memory = ForgetAssistantMemory.Field()
    wipe_assistant_memory = WipeAssistantMemory.Field()
