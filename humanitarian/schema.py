import graphene
from django.db.models import Q
from graphene_django import DjangoObjectType
from graphql_jwt.decorators import login_required

from security.models import IdentityVerification

from .models import (
    HumanitarianCampaign,
    HumanitarianDonation,
    HumanitarianProofLink,
    HumanitarianRelease,
    HumanitarianVolunteerApplication,
)


class HumanitarianProofLinkType(DjangoObjectType):
    class Meta:
        model = HumanitarianProofLink
        fields = ('url', 'title', 'platform', 'position')


class HumanitarianReleaseType(DjangoObjectType):
    proof_links = graphene.List(HumanitarianProofLinkType)
    volunteer_name = graphene.String()

    class Meta:
        model = HumanitarianRelease
        fields = (
            'public_id',
            'amount',
            'status',
            'purpose',
            'public_note',
            'transaction_hash',
            'released_at',
            'created_at',
        )

    def resolve_proof_links(self, info):
        return self.proof_links.filter(is_public=True).order_by('position', 'created_at')

    def resolve_volunteer_name(self, info):
        user = self.volunteer_application.user
        return user.get_full_name() or user.username or 'Voluntario Confio'


class HumanitarianDonationType(DjangoObjectType):
    class Meta:
        model = HumanitarianDonation
        fields = (
            'public_id',
            'donor_display_name',
            'amount',
            'status',
            'transaction_hash',
            'donated_at',
        )


class HumanitarianCampaignType(DjangoObjectType):
    releases = graphene.List(HumanitarianReleaseType, limit=graphene.Int(default_value=20))
    donations = graphene.List(HumanitarianDonationType, limit=graphene.Int(default_value=20))

    class Meta:
        model = HumanitarianCampaign
        fields = (
            'public_id',
            'slug',
            'title',
            'country_code',
            'description',
            'volunteer_section_title',
            'volunteer_section_subtitle',
            'volunteer_service_area_placeholder',
            'volunteer_notes_placeholder',
            'volunteer_cta_label',
            'status',
            'goal_amount',
            'total_donated',
            'total_released',
            'donation_count',
            'release_count',
            'vault_address',
            'updated_at',
        )

    def resolve_releases(self, info, limit=20):
        return self.releases.filter(
            status__in=['confirmed', 'proof_pending', 'proof_published']
        ).select_related('volunteer_application__user').prefetch_related('proof_links').order_by('-released_at', '-created_at')[:limit]

    def resolve_donations(self, info, limit=20):
        return self.donations.filter(status='confirmed').order_by('-donated_at')[:limit]


class HumanitarianVolunteerApplicationType(DjangoObjectType):
    has_verified_country_kyc = graphene.Boolean()
    has_verified_venezuelan_kyc = graphene.Boolean()

    class Meta:
        model = HumanitarianVolunteerApplication
        fields = ('public_id', 'status', 'service_area', 'local_phone', 'notes', 'created_at', 'updated_at')

    def resolve_has_verified_country_kyc(self, info):
        return self.has_verified_country_kyc

    def resolve_has_verified_venezuelan_kyc(self, info):
        return self.has_verified_country_kyc


class HumanitarianQueries(graphene.ObjectType):
    humanitarian_campaign = graphene.Field(HumanitarianCampaignType, slug=graphene.String(required=True))
    active_humanitarian_campaigns = graphene.List(HumanitarianCampaignType)
    active_venezuela_humanitarian_campaign = graphene.Field(HumanitarianCampaignType)
    my_humanitarian_volunteer_application = graphene.Field(HumanitarianVolunteerApplicationType, slug=graphene.String(required=True))

    def resolve_humanitarian_campaign(self, info, slug):
        return HumanitarianCampaign.objects.filter(slug=slug, status__iregex='^(active|paused|closed)$').first()

    def resolve_active_humanitarian_campaigns(self, info):
        return HumanitarianCampaign.active_campaigns()

    def resolve_active_venezuela_humanitarian_campaign(self, info):
        return HumanitarianCampaign.objects.filter(slug='venezuela-2026-earthquake', status__iexact='active').first()

    @login_required
    def resolve_my_humanitarian_volunteer_application(self, info, slug):
        campaign = HumanitarianCampaign.objects.filter(slug=slug).first()
        if not campaign:
            return None
        return HumanitarianVolunteerApplication.objects.filter(user=info.context.user, campaign=campaign).first()


class ApplyHumanitarianVolunteer(graphene.Mutation):
    class Arguments:
        campaign_slug = graphene.String(required=True)
        service_area = graphene.String(required=False)
        local_phone = graphene.String(required=False)
        notes = graphene.String(required=False)

    success = graphene.Boolean()
    error = graphene.String()
    application = graphene.Field(HumanitarianVolunteerApplicationType)

    @login_required
    def mutate(self, info, campaign_slug, service_area='', local_phone='', notes=''):
        user = info.context.user
        campaign = HumanitarianCampaign.objects.filter(slug=campaign_slug, status__iexact='active').first()
        if not campaign:
            return ApplyHumanitarianVolunteer(success=False, error='campaign_not_active')

        campaign_country = (campaign.country_code or 'VEN').upper()
        has_country_kyc = IdentityVerification.objects.filter(
            Q(verified_country__iexact=campaign_country)
            | Q(verified_nationality__iexact=campaign_country)
            | Q(document_issuing_country__iexact=campaign_country),
            user=user,
            status='verified',
            deleted_at__isnull=True,
        ).exists()
        if not has_country_kyc:
            return ApplyHumanitarianVolunteer(success=False, error='country_kyc_required')

        application, _ = HumanitarianVolunteerApplication.objects.update_or_create(
            user=user,
            campaign=campaign,
            defaults={
                'service_area': service_area or '',
                'local_phone': local_phone or '',
                'notes': notes or '',
            },
        )
        return ApplyHumanitarianVolunteer(success=True, error='', application=application)


class HumanitarianMutations(graphene.ObjectType):
    apply_humanitarian_volunteer = ApplyHumanitarianVolunteer.Field()
