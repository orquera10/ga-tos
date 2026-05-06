from django import forms
from django.contrib.auth import get_user_model
from .models import Presupuesto, PresupuestoCompartido, Categoria, Gasto, Ingreso
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
            attrs={'type': 'date', 'class': 'form-control'},
            format='%Y-%m-%d'
        ),
        input_formats=['%Y-%m-%d'],
        initial=timezone.now().date()
    )
    fecha_fin = forms.DateField(
        widget=forms.DateInput(
            attrs={'type': 'date', 'class': 'form-control'},
            format='%Y-%m-%d'
        ),
        input_formats=['%Y-%m-%d'],
        initial=timezone.now().date()
    )
    
    class Meta:
        model = Presupuesto
        fields = ['nombre', 'descripcion', 'fecha_inicio', 'fecha_fin', 'monto_total', 'moneda']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'monto_total': forms.NumberInput(attrs={'class': 'form-control'})
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['fecha_inicio'] = self.instance.fecha_inicio
            self.initial['fecha_fin'] = self.instance.fecha_fin

class CategoriaForm(CapitalizeFieldsMixin, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion']


class CompartirPresupuestoForm(forms.ModelForm):
    usuario = forms.CharField(
        label='Usuario o email',
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'usuario@email.com'})
    )

    class Meta:
        model = PresupuestoCompartido
        fields = ['usuario', 'permiso']
        widgets = {
            'permiso': forms.Select(attrs={'class': 'form-select'})
        }

    def __init__(self, *args, presupuesto=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.presupuesto = presupuesto

    def clean_usuario(self):
        value = self.cleaned_data['usuario'].strip()
        User = get_user_model()
        user = User.objects.filter(email__iexact=value).first() or User.objects.filter(username__iexact=value).first()
        if not user:
            raise forms.ValidationError('No encontramos un usuario con ese usuario o email.')
        if self.presupuesto and self.presupuesto.usuario_id == user.id:
            raise forms.ValidationError('Ese usuario ya es el dueño del presupuesto.')
        return user

    def save(self, commit=True):
        user = self.cleaned_data['usuario']
        permiso = self.cleaned_data['permiso']
        obj, _ = PresupuestoCompartido.objects.update_or_create(
            presupuesto=self.presupuesto,
            usuario=user,
            defaults={'permiso': permiso},
        )
        return obj

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
        input_formats=['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'],
        required=True
    )

    class Meta:
        model = Gasto
        fields = ['nombre', 'categoria', 'monto', 'fecha', 'descripcion', 'presupuesto_pk']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'})
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Mostrar la fecha existente al editar, o la fecha actual al crear.
        if self.instance and self.instance.pk and self.instance.fecha:
            # Asegurarse de que la fecha esté en la zona horaria local para mostrarla correctamente
            local_dt = timezone.localtime(self.instance.fecha) if timezone.is_aware(self.instance.fecha) else self.instance.fecha
        else:
            local_dt = timezone.localtime(timezone.now())
        self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def save(self, commit=True):
        # Usar siempre la fecha enviada por el formulario.
        if self.cleaned_data.get('fecha'):
            self.instance.fecha = self.cleaned_data['fecha']
        return super().save(commit)

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return monto


class IngresoForm(CapitalizeFieldsMixin, forms.ModelForm):
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
        input_formats=['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'],
        required=True
    )

    class Meta:
        model = Ingreso
        fields = ['nombre', 'monto', 'fecha', 'descripcion', 'presupuesto_pk']
        widgets = {
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01'}),
            'nombre': forms.TextInput(attrs={'class': 'form-control'})
        }
        
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Solo mostrar el campo de fecha si estamos editando un ingreso existente
        if self.instance and self.instance.pk and self.instance.fecha:
            # Asegurarse de que la fecha esté en la zona horaria local para mostrarla correctamente
            local_dt = timezone.localtime(self.instance.fecha) if timezone.is_aware(self.instance.fecha) else self.instance.fecha
        else:
            local_dt = timezone.localtime(timezone.now())
        self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def save(self, commit=True):
        # Para nuevos ingresos, la fecha ya se establece en el modelo
        # Para ediciones, usar la fecha del formulario sin conversión de zona horaria
        if self.cleaned_data.get('fecha'):
            self.instance.fecha = self.cleaned_data['fecha']
        return super().save(commit)

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return monto


