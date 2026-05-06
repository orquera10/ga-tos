from django.core import serializers
from django.contrib import admin, messages
from django.core.serializers.base import DeserializationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import path


def admin_action_description(description):
    def decorator(func):
        func.short_description = description
        return func
    return decorator


class ExportSelectedJsonMixin:
    actions = ('export_selected_json',)

    @admin_action_description('Exportar seleccionados a JSON')
    def export_selected_json(self, request, queryset):
        model_name = self.model._meta.model_name
        data = serializers.serialize('json', queryset, indent=2)
        response = HttpResponse(data, content_type='application/json')
        response['Content-Disposition'] = f'attachment; filename="{model_name}_backup.json"'
        return response


class JsonBackupAdminMixin(ExportSelectedJsonMixin):
    change_list_template = 'admin/json_backup_change_list.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                'import-json/',
                self.admin_site.admin_view(self.import_json_view),
                name=f'{self.model._meta.app_label}_{self.model._meta.model_name}_import_json',
            ),
        ]
        return custom_urls + urls

    def import_json_view(self, request):
        opts = self.model._meta
        context = {
            **self.admin_site.each_context(request),
            'opts': opts,
            'title': f'Importar backup de {opts.verbose_name_plural}',
        }

        if request.method == 'POST':
            backup_file = request.FILES.get('backup_file')
            if not backup_file:
                messages.error(request, 'Selecciona un archivo JSON.')
                return redirect(request.path)

            try:
                raw_data = backup_file.read().decode('utf-8')
                objects = list(serializers.deserialize('json', raw_data))
                imported = 0
                for obj in objects:
                    if obj.object._meta.label_lower != opts.label_lower:
                        messages.error(request, 'El archivo contiene datos de otro modelo.')
                        return redirect(request.path)
                    obj.save()
                    imported += 1
            except (UnicodeDecodeError, DeserializationError, ValueError) as exc:
                messages.error(request, f'No se pudo importar el archivo: {exc}')
                return redirect(request.path)

            messages.success(request, f'Se importaron {imported} registros.')
            return redirect(f'../')

        return render(request, 'admin/json_backup_import.html', context)
