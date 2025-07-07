from django.db import models
from django.utils import timezone

class Categoria(models.Model):
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)

    def __str__(self):
        return self.nombre

class Presupuesto(models.Model):
    MONEDAS = [
        ('USD', 'Dólar Estadounidense'),
        ('ARS', 'Peso Argentino'),
        ('BOB', 'Boliviano'),
        ('EUR', 'Euro'),
    ]
    
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    monto_total = models.DecimalField(max_digits=10, decimal_places=2)
    monto_restante = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    moneda = models.CharField(max_length=3, choices=MONEDAS, default='ARS')
    fecha_creacion = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.nombre} - {self.fecha_inicio} a {self.fecha_fin}"

    def actualizar_monto_restante(self):
        # Calcular el monto restante restando todos los gastos del monto total
        total_gastos = self.gastos.aggregate(total=models.Sum('monto'))['total'] or 0
        self.monto_restante = self.monto_total - total_gastos
        self.save()

    def porcentaje_gastado(self):
        """Calcula el porcentaje gastado del presupuesto."""
        total_gastos = self.gastos.aggregate(total=models.Sum('monto'))['total'] or 0
        if self.monto_total == 0:
            return 0
        porcentaje = (total_gastos / self.monto_total) * 100
        return min(max(porcentaje, 0), 100)

class Gasto(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='gastos')
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateField()

    def clean(self):
        super().clean()
        
        # Validar que el monto no sea negativo
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        # Si no se especifica una moneda, usar la del presupuesto
        if not hasattr(self, 'moneda'):
            self.moneda = self.presupuesto.moneda
        
        super().save(*args, **kwargs)
        # Actualizar el monto restante del presupuesto
        self.presupuesto.actualizar_monto_restante()

    def __str__(self):
        return f"{self.nombre} - ${self.monto}"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Actualizar el monto restante del presupuesto
        self.presupuesto.actualizar_monto_restante()

    def delete(self, *args, **kwargs):
        # Restaurar el monto al presupuesto antes de eliminar el gasto
        self.presupuesto.monto_restante += self.monto
        self.presupuesto.save()
        super().delete(*args, **kwargs)
