from django import forms
from .models import Presupuesto, Categoria, Gasto

from django.utils import timezone

class PresupuestoForm(forms.ModelForm):
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

class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nombre', 'descripcion']

class GastoForm(forms.ModelForm):
    presupuesto_pk = forms.IntegerField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Gasto
        fields = ['nombre', 'categoria', 'monto', 'fecha', 'descripcion', 'presupuesto_pk']
        widgets = {
            'fecha': forms.DateInput(attrs={'type': 'date', 'class': 'form-control'}),
            'descripcion': forms.Textarea(attrs={'rows': 3, 'class': 'form-control'})
        }

    def clean_monto(self):
        monto = self.cleaned_data.get('monto')
        if monto is not None and monto <= 0:
            raise forms.ValidationError('El monto debe ser mayor a cero')
        return monto

    def clean_fecha(self):
        fecha = self.cleaned_data.get('fecha')
        presupuesto_pk = self.data.get('presupuesto_pk')
        
        if fecha and presupuesto_pk:
            try:
                presupuesto = Presupuesto.objects.get(pk=presupuesto_pk)
                if fecha < presupuesto.fecha_inicio or fecha > presupuesto.fecha_fin:
                    raise forms.ValidationError(
                        f'La fecha debe estar entre {presupuesto.fecha_inicio.strftime("%d/%m/%Y")} y {presupuesto.fecha_fin.strftime("%d/%m/%Y")}'
                    )
            except Presupuesto.DoesNotExist:
                raise forms.ValidationError('Presupuesto no encontrado')
        
        return fecha
