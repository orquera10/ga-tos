from django.db import models
from django.utils import timezone

class CalculadoraDivisa(models.Model):
    MONEDAS = [
        ('USD', 'Dólar Estadounidense'),
        ('EUR', 'Euro'),
        ('ARS', 'Peso Argentino'),
        ('BOB', 'Boliviano'),
        ('BRL', 'Real Brasileño'),
        ('CLP', 'Peso Chileno'),
        ('MXN', 'Peso Mexicano'),
        ('PEN', 'Sol Peruano'),
        ('UYU', 'Peso Uruguayo'),
        ('PYG', 'Guaraní Paraguayo'),
    ]

    nombre = models.CharField(max_length=100, help_text="Nombre descriptivo para esta relación de conversión")
    moneda_origen = models.CharField(max_length=3, choices=MONEDAS)
    moneda_destino = models.CharField(max_length=3, choices=MONEDAS)
    relacion = models.DecimalField(
        max_digits=20, 
        decimal_places=10,
        help_text="Relación de conversión (1 moneda_origen = X moneda_destino)"
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-fecha_creacion']
        verbose_name = 'Calculadora de Divisa'
        verbose_name_plural = 'Calculadoras de Divisas'

    def __str__(self):
        return f"{self.nombre} ({self.moneda_origen} a {self.moneda_destino})"

    def convertir(self, monto, direccion='directa'):
        """
        Convierte un monto entre las monedas en la dirección especificada.
        
        Args:
            monto: Cantidad a convertir
            direccion: 'directa' para moneda_origen -> moneda_destino
                     'inversa' para moneda_destino -> moneda_origen
        """
        monto = float(monto)
        if direccion == 'directa':
            return round(monto * float(self.relacion), 2)
        else:  # inversa
            return round(monto / float(self.relacion), 2)
            
    def get_moneda_origen_display_name(self):
        """Devuelve el nombre completo de la moneda de origen"""
        return dict(self.MONEDAS).get(self.moneda_origen, self.moneda_origen)
        
    def get_moneda_destino_display_name(self):
        """Devuelve el nombre completo de la moneda de destino"""
        return dict(self.MONEDAS).get(self.moneda_destino, self.moneda_destino)
