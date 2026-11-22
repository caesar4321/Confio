"""GraphQL for the calendar slice. Its own mutation: older servers reject only this."""
import graphene
from graphql_jwt.decorators import login_required

from inbox.schema import get_context_models

from . import calendar_context


class AnalyzeAssistantCalendar(graphene.Mutation):
    class Arguments:
        titles = graphene.List(graphene.NonNull(graphene.String), required=True,
                               description='Titles the person ticked. Used for this request, never stored.')
        consent_version = graphene.Int(required=True)

    success = graphene.Boolean(required=True)
    error = graphene.String()
    error_code = graphene.String()
    kinds = graphene.List(graphene.NonNull(graphene.String), required=True,
                          description='One per title, same order: payment | ticket | trip | deadline | none')

    @classmethod
    @login_required
    def mutate(cls, root, info, titles, consent_version):
        user, account, _business, jwt_context = get_context_models(info)
        try:
            kinds = calendar_context.classify(user, account, jwt_context, titles, consent_version)
        except calendar_context.CalendarRefused as exc:
            return cls(success=False, error=exc.message, error_code=exc.code, kinds=[])
        return cls(success=True, kinds=kinds)


class Mutation(graphene.ObjectType):
    analyze_assistant_calendar = AnalyzeAssistantCalendar.Field()
