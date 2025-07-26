"""
Enhanced Admin Mixins for Confío
Provides advanced features like export, bulk actions, and enhanced filtering
"""
import csv
import json
from datetime import datetime
from django.contrib import admin
from django.http import HttpResponse
from django.utils.html import format_html
from django.db.models import Q
from django.contrib import messages
from django.utils import timezone


class ExportCsvMixin:
    """Mixin to add CSV export functionality to admin"""
    
    def export_as_csv(self, request, queryset):
        meta = self.model._meta
        field_names = [field.name for field in meta.fields]
        
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
        writer = csv.writer(response)
        
        # Write header
        writer.writerow(field_names)
        
        # Write data
        for obj in queryset:
            writer.writerow([getattr(obj, field) for field in field_names])
        
        return response
    
    export_as_csv.short_description = "📥 Export selected as CSV"


class ExportJsonMixin:
    """Mixin to add JSON export functionality to admin"""
    
    def export_as_json(self, request, queryset):
        meta = self.model._meta
        
        data = []
        for obj in queryset:
            obj_data = {}
            for field in meta.fields:
                value = getattr(obj, field.name)
                if hasattr(value, 'isoformat'):
                    value = value.isoformat()
                elif hasattr(value, 'pk'):
                    value = value.pk
                else:
                    value = str(value)
                obj_data[field.name] = value
            data.append(obj_data)
        
        response = HttpResponse(content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename={meta.verbose_name_plural}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
        json.dump(data, response, indent=2)
        
        return response
    
    export_as_json.short_description = "📥 Export selected as JSON"


class BulkUpdateMixin:
    """Mixin to add bulk update actions"""
    
    def bulk_activate(self, request, queryset):
        updated = queryset.update(is_active=True, updated_at=timezone.now())
        self.message_user(request, f'{updated} items activated successfully.', messages.SUCCESS)
    bulk_activate.short_description = "✅ Activate selected items"
    
    def bulk_deactivate(self, request, queryset):
        updated = queryset.update(is_active=False, updated_at=timezone.now())
        self.message_user(request, f'{updated} items deactivated successfully.', messages.WARNING)
    bulk_deactivate.short_description = "⏸️ Deactivate selected items"


class AdvancedSearchMixin:
    """Mixin to enhance search functionality"""
    
    def get_search_results(self, request, queryset, search_term):
        queryset, use_distinct = super().get_search_results(request, queryset, search_term)
        
        # Add support for quoted exact search
        if search_term.startswith('"') and search_term.endswith('"'):
            exact_term = search_term[1:-1]
            or_queries = [Q(**{field + '__iexact': exact_term}) for field in self.search_fields]
            queryset = queryset.filter(Q(*or_queries, _connector=Q.OR))
        
        # Add support for negative search with -
        elif search_term.startswith('-'):
            exclude_term = search_term[1:]
            or_queries = [Q(**{field + '__icontains': exclude_term}) for field in self.search_fields]
            queryset = queryset.exclude(Q(*or_queries, _connector=Q.OR))
        
        return queryset, use_distinct


class StatusColorMixin:
    """Mixin to add colored status displays"""
    
    def colored_status(self, obj):
        """Override this method to define status colors"""
        status = getattr(obj, 'status', None)
        if not status:
            return '-'
        
        colors = {
            'active': '#10B981',
            'inactive': '#6B7280',
            'pending': '#F59E0B',
            'completed': '#3B82F6',
            'failed': '#EF4444',
            'disputed': '#DC2626',
        }
        
        color = colors.get(status.lower(), '#6B7280')
        return format_html(
            '<span style="background-color: {}; color: white; padding: 4px 8px; '
            'border-radius: 4px; font-weight: bold; font-size: 11px;">{}</span>',
            color,
            status.upper()
        )
    colored_status.short_description = 'Status'


class InlineCountMixin:
    """Mixin to show count of inline items"""
    
    def get_inline_count(self, obj, inline_model, related_name):
        """Get count of related inline items"""
        count = getattr(obj, related_name).count()
        if count > 0:
            return format_html(
                '<span style="background-color: #3B82F6; color: white; '
                'padding: 2px 8px; border-radius: 12px; font-size: 12px;">{}</span>',
                count
            )
        return format_html('<span style="color: #999;">0</span>')


class TimestampAdminMixin:
    """Mixin to add timestamp displays with relative time"""
    
    def created_display(self, obj):
        if obj.created_at:
            return format_html(
                '<span title="{}">{} ago</span>',
                obj.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                self._timesince(obj.created_at)
            )
        return '-'
    created_display.short_description = 'Created'
    
    def updated_display(self, obj):
        if obj.updated_at:
            return format_html(
                '<span title="{}">{} ago</span>',
                obj.updated_at.strftime('%Y-%m-%d %H:%M:%S'),
                self._timesince(obj.updated_at)
            )
        return '-'
    updated_display.short_description = 'Updated'
    
    def _timesince(self, dt):
        """Get human-readable time since datetime"""
        from django.utils.timesince import timesince
        return timesince(dt, timezone.now())


class ReadOnlyInlineMixin:
    """Mixin to make inline admin read-only"""
    
    def has_add_permission(self, request, obj=None):
        return False
    
    def has_change_permission(self, request, obj=None):
        return False
    
    def has_delete_permission(self, request, obj=None):
        return False


class AuditMixin:
    """Mixin to add audit trail functionality"""
    
    def save_model(self, request, obj, form, change):
        if change:
            # Log what changed
            if form.changed_data:
                changes = []
                for field in form.changed_data:
                    old_value = form.initial.get(field)
                    new_value = form.cleaned_data.get(field)
                    changes.append(f"{field}: {old_value} → {new_value}")
                
                self.log_change(
                    request,
                    obj,
                    f"Changed: {', '.join(changes[:3])}{'...' if len(changes) > 3 else ''}"
                )
        
        super().save_model(request, obj, form, change)


class FilterByDateRangeMixin:
    """Mixin to add date range filtering"""
    
    date_hierarchy = 'created_at'  # Default field, override as needed
    
    def changelist_view(self, request, extra_context=None):
        # Add date range presets to context
        extra_context = extra_context or {}
        extra_context['date_ranges'] = [
            ('today', 'Today'),
            ('yesterday', 'Yesterday'),
            ('week', 'This Week'),
            ('month', 'This Month'),
            ('quarter', 'This Quarter'),
            ('year', 'This Year'),
        ]
        
        return super().changelist_view(request, extra_context=extra_context)


class EnhancedAdminMixin(
    ExportCsvMixin,
    ExportJsonMixin,
    AdvancedSearchMixin,
    StatusColorMixin,
    TimestampAdminMixin,
    AuditMixin
):
    """Combined mixin with all enhancements"""
    
    def get_actions(self, request):
        actions = super().get_actions(request)
        # Add export actions by default
        actions['export_as_csv'] = (self.export_as_csv, 'export_as_csv', "📥 Export selected as CSV")
        actions['export_as_json'] = (self.export_as_json, 'export_as_json', "📥 Export selected as JSON")
        return actions