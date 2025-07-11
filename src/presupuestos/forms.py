from django import forms
from .models import Presupuesto, Categoria, Gasto
from django.utils import timezone

class CapitalizeFieldsMixin:
    """
    Mixin para capitalizar automáticamente los campos de texto
    """
    def clean(self):
        cleaned_data = super().clean()
        for field_name, field in self.fields.items():
            if isinstance(field, (forms.CharField, forms.TextInput, forms.Textarea)):
                if field_name in cleaned_data and cleaned_data[field_name]:
                    # Capitaliza solo la primera letra de toda la cadena
                    value = str(cleaned_data[field_name])
                    if value:  # Asegurarse de que el valor no esté vacío
                        cleaned_data[field_name] = value[0].upper() + value[1:].lower()
        return cleaned_data

class PresupuestoForm(CapitalizeFieldsMixin, forms.ModelForm):
    fecha_inicio = forms.DateField(
        widget=forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control', 'value': timezone.now().date().isoformat()}
        ),
        initial=timezone.now().date()
    )
    fecha_fin = forms.DateField(
        widget=forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control', 'value': timezone.now().date().isoformat()}
        ),
        initial=timezone.now().date()
    )
    
    class Meta:
        model = Presupuesto
        fields = ['nombre', 'descripcion', 'fecha_inicio', 'fecha_fin', 'monto_total', 'moneda']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'monto_total': forms.NumberInput(attrs={'class': 'form-control'})
        }

class CategoriaForm(CapitalizeFieldsMixin, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion']

class GastoForm(CapitalizeFieldsMixin, forms.ModelForm):
    presupuesto_pk = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    fecha = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'step': '1'  # Permite segundos
            },
            format='%Y-%m-%dT%H:%M:%S'
        ),
        required=False  # No requerido para nuevos gastos
    )

    class Meta:
        model = Gasto
        fields = ['nombre', 'categoria', 'monto', 'fecha', 'descripcion', 'presupuesto_pk']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'})
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo mostrar el campo de fecha si estamos editando un gasto existente
        if not self.instance or not self.instance.pk:
            self.fields['fecha'].widget = forms.HiddenInput()
        elif self.instance.fecha:
            # Asegurarse de que la fecha esté en la zona horaria local para mostrarla correctamente
            local_dt = timezone.localtime(self.instance.fecha) if timezone.is_aware(self.instance.fecha) else self.instance.fecha
            self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def save(self, commit=True):
        # Para nuevos gastos, la fecha ya se establece en el modelo
        # Para ediciones, usar la fecha del formulario sin conversión de zona horaria
        if 'fecha' in self.changed_data and self.cleaned_data.get('fecha'):
            self.instance.fecha = self.cleaned_data['fecha']
        return super().save(commit)

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return monto


