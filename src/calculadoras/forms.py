from django import forms
from decimal import Decimal
from .models import CalculadoraDivisa

class CalculadoraDivisaForm(forms.ModelForm):
    monto_origen = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal('0.01'),
        initial=1,
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01'
        })
    )
    
    monto_destino = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal('0.0000000001'),
        required=True,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.0000000001',
            'min': '0.0000000001'
        })
    )
    
    class Meta:
        model = CalculadoraDivisa
        fields = ['nombre', 'moneda_origen', 'moneda_destino', 'relacion']
        widgets = {
            'nombre': forms.TextInput(attrs={'class': 'form-control'}),
            'moneda_origen': forms.Select(attrs={'class': 'form-select'}),
            'moneda_destino': forms.Select(attrs={'class': 'form-select'}),
            'relacion': forms.HiddenInput()
        }

    def clean(self):
        cleaned_data = super().clean()
        moneda_origen = cleaned_data.get('moneda_origen')
        moneda_destino = cleaned_data.get('moneda_destino')
        monto_origen = cleaned_data.get('monto_origen')
        monto_destino = cleaned_data.get('monto_destino')
        
        if moneda_origen == moneda_destino:
            raise forms.ValidationError("La moneda de origen y destino no pueden ser iguales")
        
        if monto_origen is None or monto_destino is None or monto_origen == 0:
            raise forms.ValidationError("Por favor, ingresa los montos de origen y destino")
        
        try:
            relacion = Decimal(monto_destino) / Decimal(monto_origen)
            cleaned_data['relacion'] = relacion.quantize(Decimal('0.0000000001'))
        except (TypeError, ZeroDivisionError):
            raise forms.ValidationError("Error al calcular la relación. Verifica los montos ingresados.")
        
        return cleaned_data


class ConversionForm(forms.Form):
    calculadora_id = forms.IntegerField(widget=forms.HiddenInput())
    monto = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        min_value=Decimal('0.01'),
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01',
            'placeholder': 'Ingrese el monto a convertir'
        })
    )

    def __init__(self, *args, **kwargs):
        calculadora = kwargs.pop('calculadora', None)
        super().__init__(*args, **kwargs)
        if calculadora:
            self.fields['calculadora_id'].initial = calculadora.id

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            # Para calculadoras existentes, mostramos los montos como readonly
            self.fields['monto_origen'].initial = 1
            self.fields['monto_destino'].initial = float(self.instance.relacion)
            self.fields['monto_destino'].widget.attrs['readonly'] = True
            
            # Establecer valores iniciales para los campos del modelo
            self.fields['nombre'].initial = self.instance.nombre
            self.fields['moneda_origen'].initial = self.instance.moneda_origen
            self.fields['moneda_destino'].initial = self.instance.moneda_destino
            self.fields['relacion'].initial = self.instance.relacion
        else:
            # Para nueva calculadora, ambos campos deben estar habilitados
            self.fields['monto_destino'].widget.attrs['readonly'] = False
    
    def clean(self):
        cleaned_data = super().clean()
        moneda_origen = cleaned_data.get('moneda_origen')
        moneda_destino = cleaned_data.get('moneda_destino')
        monto_origen = cleaned_data.get('monto_origen')
        monto_destino = cleaned_data.get('monto_destino')
        
        if moneda_origen == moneda_destino:
            raise forms.ValidationError("La moneda de origen y destino no pueden ser iguales")
        
        # Si se proporcionó monto_destino, calcular la relación
        if monto_destino is not None and monto_origen is not None and monto_origen != 0:
            try:
                relacion = monto_destino / monto_origen
                cleaned_data['relacion'] = round(relacion, 10)
            except (TypeError, ZeroDivisionError):
                raise forms.ValidationError("Error al calcular la relación. Verifica los montos ingresados.")
        
        return cleaned_data

class ConversionForm(forms.Form):
    def __init__(self, *args, **kwargs):
        self.calculadora = kwargs.pop('calculadora', None)
        super().__init__(*args, **kwargs)
        
        # Si no hay una calculadora específica, mostramos el selector
        if not self.calculadora:
            self.fields['calculadora'] = forms.ModelChoiceField(
                queryset=CalculadoraDivisa.objects.all(),
                widget=forms.Select(attrs={
                    'class': 'form-select',
                    'id': 'id_calculadora'
                }),
                label="Seleccionar calculadora",
                required=True
            )
        else:
            # Si hay una calculadora específica, usamos un campo oculto
            self.fields['calculadora'] = forms.ModelChoiceField(
                queryset=CalculadoraDivisa.objects.filter(pk=self.calculadora.pk),
                widget=forms.HiddenInput(),
                required=True,
                initial=self.calculadora.id
            )
    
    monto = forms.DecimalField(
        max_digits=20,
        decimal_places=2,
        widget=forms.NumberInput(attrs={
            'class': 'form-control',
            'step': '0.01',
            'min': '0.01',
            'id': 'id_monto'
        }),
        initial=1.00,
        required=True
    )
    
    def clean(self):
        cleaned_data = super().clean()
        if 'calculadora' in cleaned_data:
            self.calculadora = cleaned_data['calculadora']
        return cleaned_data
        return cleaned_data
