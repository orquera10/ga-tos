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
        # Calcular el total de gastos e ingresos
        total_gastos = self.gastos.aggregate(total=models.Sum('monto'))['total'] or 0
        total_ingresos = self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
        # El monto restante es el monto total (incluyendo ingresos) menos los gastos
        self.monto_restante = (self.monto_total + total_ingresos) - total_gastos
        self.save()

    def porcentaje_gastado(self):
        """Calcula el porcentaje gastado del presupuesto."""
        total_gastos = self.gastos.aggregate(total=models.Sum('monto'))['total'] or 0
        total_ingresos = self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
        # El monto total incluye tanto el presupuesto inicial como los ingresos adicionales
        monto_total_con_ingresos = self.monto_total + total_ingresos
        
        if monto_total_con_ingresos == 0:
            return 0
            
        porcentaje = (total_gastos / monto_total_con_ingresos) * 100
        return min(max(porcentaje, 0), 100)
        
    @property
    def total_ingresos(self):
        """Devuelve la suma total de todos los ingresos del presupuesto."""
        return self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
    def monto_total_con_ingresos(self):
        """Devuelve el monto total del presupuesto incluyendo los ingresos adicionales."""
        return self.monto_total + self.total_ingresos

class Gasto(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='gastos')
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        
        # Validar que el monto no sea negativo
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        # Si es un nuevo gasto, establecer la fecha actual en hora local (sin zona horaria)
        if not self.pk and not self.fecha:
            self.fecha = timezone.localtime(timezone.now())
        
        # Si la fecha tiene zona horaria, convertir a hora local sin zona horaria
        if timezone.is_aware(self.fecha):
            self.fecha = timezone.localtime(self.fecha).replace(tzinfo=None)
            
        super().save(*args, **kwargs)
        
        # Actualizar el monto restante del presupuesto
        if self.presupuesto:
            self.presupuesto.actualizar_monto_restante()

    def __str__(self):
        return f"{self.nombre} - ${self.monto}"

        # Actualizar el monto restante del presupuesto
        self.presupuesto.actualizar_monto_restante()

    def delete(self, *args, **kwargs):
        # Restaurar el monto al presupuesto antes de eliminar el gasto
        self.presupuesto.monto_restante += self.monto
        self.presupuesto.save()
        super().delete(*args, **kwargs)


class Ingreso(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='ingresos')
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        
        # Validar que el monto no sea negativo
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        # Si es un nuevo ingreso, establecer la fecha actual en hora local (sin zona horaria)
        if not self.pk and not self.fecha:
            self.fecha = timezone.localtime(timezone.now())
        
        # Si la fecha tiene zona horaria, convertir a hora local sin zona horaria
        if timezone.is_aware(self.fecha):
            self.fecha = timezone.localtime(self.fecha).replace(tzinfo=None)
            
        # Guardar primero el ingreso
        super().save(*args, **kwargs)
        
        # Actualizar el presupuesto usando el método actualizar_monto_restante
        if self.presupuesto:
            self.presupuesto.actualizar_monto_restante()

    def delete(self, *args, **kwargs):
        # Guardar referencia al presupuesto antes de eliminar
        presupuesto = self.presupuesto
        
        # Eliminar el ingreso
        super().delete(*args, **kwargs)
        
        # Actualizar el presupuesto usando el método actualizar_monto_restante
        if presupuesto:
            presupuesto.actualizar_monto_restante()

    def __str__(self):
        return f"{self.nombre} - ${self.monto}"
