from decimal import Decimal
from django import forms
from django.contrib.auth import get_user_model
from .models import Presupuesto, PresupuestoCompartido, Categoria, Gasto, Ingreso, CicloPrestamo, TarjetaPrestamo
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
                    value = str(cleaned_data[field_name])
                    if value:
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
    monto_total = forms.DecimalField(
        required=False,
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '0.00'})
    )
    
    class Meta:
        model = Presupuesto
        fields = [
            'nombre', 'tipo', 'monto_total', 'moneda', 'fecha_inicio', 'fecha_fin', 'descripcion',
            'deuda_inicial_prestamo', 'aporte_mensual_prestamo', 'tasa_interes_prestamo'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Gastos de Mayo, Vacaciones...'}),
            'tipo': forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo'}),
            'moneda': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Detalle o nota (opcional)...'}),
            'deuda_inicial_prestamo': forms.NumberInput(attrs={'class': 'form-control', 'step': '1000', 'placeholder': '10000000.00'}),
            'aporte_mensual_prestamo': forms.NumberInput(attrs={'class': 'form-control', 'step': '1000', 'placeholder': '600000.00'}),
            'tasa_interes_prestamo': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '4.50'}),
        }
        labels = {
            'deuda_inicial_prestamo': 'Deuda total inicial',
            'aporte_mensual_prestamo': 'Aporte mensual para amortizar',
            'tasa_interes_prestamo': 'Tasa de interés de la App (%)',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.initial['fecha_inicio'] = self.instance.fecha_inicio
            self.initial['fecha_fin'] = self.instance.fecha_fin

    def clean(self):
        cleaned_data = super().clean()
        tipo = cleaned_data.get('tipo')
        monto_total = cleaned_data.get('monto_total')
        if tipo in ['abierto', 'prestamo']:
            cleaned_data['monto_total'] = monto_total or 0
        else:
            if monto_total is None or monto_total <= 0:
                self.add_error('monto_total', 'Debes ingresar un monto inicial positivo para presupuestos de monto fijo.')
        return cleaned_data

class CategoriaForm(CapitalizeFieldsMixin, forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Alimentación, Ocio, Servicios...'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control', 'placeholder': 'Descripción opcional...'}),
        }


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
    persona = forms.CharField(
        required=False,
        max_length=60,
        label='Persona / Tag',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Hija, Victoria, Dario, Personal...',
            'autocomplete': 'off'
        })
    )
    cuenta_bancaria_nombre = forms.CharField(
        required=False,
        max_length=60,
        label='Banco / Billetera',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Brubank, Mercado Pago, Ualá...',
            'autocomplete': 'off'
        })
    )
    fecha = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'step': '1'
            },
            format='%Y-%m-%dT%H:%M:%S'
        ),
        input_formats=['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'],
        required=True
    )

    class Meta:
        model = Gasto
        fields = ['nombre', 'persona', 'monto', 'metodo_pago', 'cuenta_bancaria_nombre', 'categoria', 'fecha', 'descripcion', 'presupuesto_pk']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Almuerzo, Supermercado...'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01', 'placeholder': '0.00'}),
            'metodo_pago': forms.Select(attrs={'class': 'form-select', 'id': 'id_metodo_pago'}),
            'categoria': forms.Select(attrs={'class': 'form-select'}),
            'descripcion': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Detalle o nota (opcional)...'})
        }
        labels = {
            'metodo_pago': 'Medio de Pago'
        }
        
    def __init__(self, *args, user=None, **kwargs):
        self.user = user
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            if self.instance.persona:
                self.initial['persona'] = self.instance.persona
            if self.instance.cuenta_bancaria:
                self.initial['cuenta_bancaria_nombre'] = self.instance.cuenta_bancaria.nombre
            if self.instance.fecha:
                local_dt = timezone.localtime(self.instance.fecha) if timezone.is_aware(self.instance.fecha) else self.instance.fecha
                self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
        else:
            local_dt = timezone.localtime(timezone.now())
            self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def save(self, commit=True, user=None):
        current_user = user or self.user
        if not current_user and hasattr(self.instance, 'presupuesto') and self.instance.presupuesto:
            current_user = self.instance.presupuesto.usuario

        cuenta_nom = (self.cleaned_data.get('cuenta_bancaria_nombre') or '').strip()
        if cuenta_nom and current_user:
            from .models import CuentaBancaria
            cuenta, _ = CuentaBancaria.objects.get_or_create(
                usuario=current_user,
                nombre__iexact=cuenta_nom,
                defaults={'nombre': cuenta_nom.title()}
            )
            self.instance.cuenta_bancaria = cuenta
        elif not cuenta_nom:
            self.instance.cuenta_bancaria = None

        if 'persona' in self.cleaned_data:
            p = (self.cleaned_data.get('persona') or '').strip()
            self.instance.persona = p.title() if p else ''

        if self.cleaned_data.get('fecha'):
            self.instance.fecha = self.cleaned_data['fecha']
        if 'es_extraccion_tarjeta' in self.cleaned_data:
            self.instance.es_extraccion_tarjeta = self.cleaned_data['es_extraccion_tarjeta']
        if 'es_aporte_capital' in self.cleaned_data:
            self.instance.es_aporte_capital = self.cleaned_data['es_aporte_capital']
        if 'monto_proximo_mes' in self.cleaned_data:
            self.instance.monto_proximo_mes = self.cleaned_data['monto_proximo_mes']
        if 'tasa_interes' in self.cleaned_data:
            self.instance.tasa_interes = self.cleaned_data['tasa_interes']
        return super().save(commit)

    def clean(self):
        cleaned_data = super().clean()
        es_extraccion = cleaned_data.get('es_extraccion_tarjeta')
        monto = cleaned_data.get('monto')
        tasa = cleaned_data.get('tasa_interes')
        monto_prox = cleaned_data.get('monto_proximo_mes')
        
        if es_extraccion and monto:
            if tasa is None:
                tasa = Decimal('4.50')
            cleaned_data['tasa_interes'] = tasa
            if not monto_prox:
                cleaned_data['monto_proximo_mes'] = round(monto * (Decimal('1') + (tasa / Decimal('100'))), 2)
        return cleaned_data

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return monto


class IngresoForm(CapitalizeFieldsMixin, forms.ModelForm):
    presupuesto_pk = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    cuenta_bancaria_nombre = forms.CharField(
        required=False,
        max_length=60,
        label='Banco / Billetera',
        widget=forms.TextInput(attrs={
            'class': 'form-control',
            'placeholder': 'Ej: Brubank, Mercado Pago, Ualá...',
            'autocomplete': 'off'
        })
    )
    fecha = forms.DateTimeField(
        widget=forms.DateTimeInput(
            attrs={
                'type': 'datetime-local',
                'class': 'form-control',
                'step': '1'
            },
            format='%Y-%m-%dT%H:%M:%S'
        ),
        input_formats=['%Y-%m-%dT%H:%M:%S', '%Y-%m-%dT%H:%M'],
        required=True
    )
    tasa_interes = forms.DecimalField(
        required=False,
        initial=4.50,
        label='Tasa de interés (%)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': '4.50'})
    )
    monto_proximo_mes = forms.DecimalField(
        required=False,
        label='A pagar el mes siguiente (con interés)',
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'placeholder': 'Calculado automáticamente...'})
    )
    es_extraccion_tarjeta = forms.BooleanField(
        required=False,
        initial=False,
        label='Extracción con tarjeta en la App (con interés 4.5%)',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    es_aporte_capital = forms.BooleanField(
        required=False,
        initial=False,
        label='Aporte propio para amortizar deuda',
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'})
    )
    tarjeta_prestamo = forms.ModelChoiceField(
        queryset=TarjetaPrestamo.objects.none(),
        required=False,
        label='Tarjeta utilizada',
        widget=forms.Select(attrs={'class': 'form-select', 'id': 'id_tarjeta_prestamo'}),
        empty_label='-- Seleccionar Tarjeta --'
    )

    class Meta:
        model = Ingreso
        fields = [
            'nombre', 'monto', 'tipo_ingreso', 'cuenta_bancaria_nombre', 'fecha', 'descripcion',
            'es_extraccion_tarjeta', 'tasa_interes', 'monto_proximo_mes', 'es_aporte_capital', 'tarjeta_prestamo', 'presupuesto_pk'
        ]
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Sueldo, Cobro de honorarios...'}),
            'monto': forms.NumberInput(attrs={'class': 'form-control', 'min': '0.01', 'step': '0.01', 'placeholder': '0.00'}),
            'tipo_ingreso': forms.Select(attrs={'class': 'form-select', 'id': 'id_tipo_ingreso'}),
            'descripcion': forms.Textarea(attrs={'rows': 2, 'class': 'form-control', 'placeholder': 'Detalle o nota (opcional)...'}),
        }
        labels = {
            'tipo_ingreso': 'Medio de Ingreso'
        }
        
    def __init__(self, *args, user=None, presupuesto=None, **kwargs):
        self.user = user
        self.presupuesto = presupuesto
        super().__init__(*args, **kwargs)

        p = self.presupuesto
        if not p and self.instance and self.instance.pk and hasattr(self.instance, 'presupuesto'):
            p = self.instance.presupuesto
        
        if p and p.tipo == 'prestamo':
            self.fields['tarjeta_prestamo'].queryset = p.tarjetas_prestamo.all()
        else:
            self.fields['tarjeta_prestamo'].widget = forms.HiddenInput()

        if self.instance and self.instance.pk:
            if self.instance.cuenta_bancaria:
                self.initial['cuenta_bancaria_nombre'] = self.instance.cuenta_bancaria.nombre
            if self.instance.fecha:
                local_dt = timezone.localtime(self.instance.fecha) if timezone.is_aware(self.instance.fecha) else self.instance.fecha
                self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
            if self.instance.tarjeta_prestamo_id:
                self.initial['tarjeta_prestamo'] = self.instance.tarjeta_prestamo_id
        else:
            local_dt = timezone.localtime(timezone.now())
            self.initial['fecha'] = local_dt.strftime('%Y-%m-%dT%H:%M:%S')
    
    def save(self, commit=True, user=None):
        current_user = user or self.user
        if not current_user and hasattr(self.instance, 'presupuesto') and self.instance.presupuesto:
            current_user = self.instance.presupuesto.usuario

        cuenta_nom = (self.cleaned_data.get('cuenta_bancaria_nombre') or '').strip()
        if cuenta_nom and current_user:
            from .models import CuentaBancaria
            cuenta, _ = CuentaBancaria.objects.get_or_create(
                usuario=current_user,
                nombre__iexact=cuenta_nom,
                defaults={'nombre': cuenta_nom.title()}
            )
            self.instance.cuenta_bancaria = cuenta
        elif not cuenta_nom:
            self.instance.cuenta_bancaria = None

        if self.cleaned_data.get('fecha'):
            self.instance.fecha = self.cleaned_data['fecha']
        if 'es_extraccion_tarjeta' in self.cleaned_data:
            self.instance.es_extraccion_tarjeta = self.cleaned_data['es_extraccion_tarjeta']
        if 'es_aporte_capital' in self.cleaned_data:
            self.instance.es_aporte_capital = self.cleaned_data['es_aporte_capital']
        if 'monto_proximo_mes' in self.cleaned_data:
            self.instance.monto_proximo_mes = self.cleaned_data['monto_proximo_mes']
        if 'tasa_interes' in self.cleaned_data:
            self.instance.tasa_interes = self.cleaned_data['tasa_interes']
        if 'tarjeta_prestamo' in self.cleaned_data and self.cleaned_data['tarjeta_prestamo']:
            self.instance.tarjeta_prestamo = self.cleaned_data['tarjeta_prestamo']
            if not self.cleaned_data.get('nombre'):
                self.instance.nombre = self.instance.tarjeta_prestamo.nombre
        return super().save(commit)

    def clean(self):
        cleaned_data = super().clean()
        es_extraccion = cleaned_data.get('es_extraccion_tarjeta')
        tarjeta = cleaned_data.get('tarjeta_prestamo')
        nombre = cleaned_data.get('nombre')
        if tarjeta and not nombre:
            cleaned_data['nombre'] = tarjeta.nombre
        monto = cleaned_data.get('monto')
        tasa = cleaned_data.get('tasa_interes')
        monto_prox = cleaned_data.get('monto_proximo_mes')
        
        if es_extraccion and monto:
            if tasa is None:
                tasa = Decimal('4.50')
            cleaned_data['tasa_interes'] = tasa
            if not monto_prox:
                cleaned_data['monto_proximo_mes'] = round(monto * (Decimal('1') + (tasa / Decimal('100'))), 2)
        return cleaned_data

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return monto


class TarjetaPrestamoForm(CapitalizeFieldsMixin, forms.ModelForm):
    class Meta:
        model = TarjetaPrestamo
        fields = ['nombre', 'dia_cierre_habitual', 'dia_vencimiento_habitual', 'proxima_fecha_cierre', 'proxima_fecha_vencimiento', 'nota']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Patagonia Rubén, Naranja...'}),
            'dia_cierre_habitual': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 31}),
            'dia_vencimiento_habitual': forms.NumberInput(attrs={'class': 'form-control', 'min': 1, 'max': 31}),
            'proxima_fecha_cierre': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'proxima_fecha_vencimiento': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'nota': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Nota adicional...'}),
        }
        labels = {
            'nombre': 'Nombre de la Tarjeta',
            'dia_cierre_habitual': 'Día de Cierre Habitual',
            'dia_vencimiento_habitual': 'Día de Vencimiento Habitual',
            'proxima_fecha_cierre': 'Próxima Fecha de Cierre Exacta',
            'proxima_fecha_vencimiento': 'Próxima Fecha de Vencimiento Exacta',
            'nota': 'Nota o Titular',
        }


class CerrarCicloPrestamoForm(forms.Form):
    nuevo_nombre = forms.CharField(
        max_length=100,
        label="Nombre del Nuevo Período",
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ej: Período Diciembre 2026 (desde 20/11)'})
    )
    nueva_fecha_inicio = forms.DateField(
        label="Fecha de Inicio del Nuevo Período",
        widget=forms.DateInput(attrs={'type': 'date', 'class': 'form-control'})
    )
    deuda_a_devolver = forms.DecimalField(
        label="Deuda a Devolver en el Nuevo Período ($)",
        widget=forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01'})
    )
