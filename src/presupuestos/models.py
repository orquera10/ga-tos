from django.db import models
from django.conf import settings
from django.core.exceptions import ValidationError
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
    TIPOS = [
        ('fijo', 'Monto fijo inicial'),
        ('abierto', 'Flujo continuo (Abierto)'),
    ]
    
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, related_name='presupuestos', null=True, blank=True)
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField()
    tipo = models.CharField(max_length=20, choices=TIPOS, default='fijo')
    monto_total = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    monto_restante = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    moneda = models.CharField(max_length=3, choices=MONEDAS, default='ARS')
    fecha_creacion = models.DateTimeField(default=timezone.now)

    def __str__(self):
        return f"{self.nombre} - {self.fecha_inicio} a {self.fecha_fin}"

    def actualizar_monto_restante(self):
        # Gastos que descuentan ahora (excluye tarjeta que impactará el mes siguiente)
        total_gastos = self.gastos.exclude(metodo_pago='tarjeta').aggregate(total=models.Sum('monto'))['total'] or 0
        total_ingresos = self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
        if self.tipo == 'abierto':
            self.monto_restante = total_ingresos - total_gastos
        else:
            self.monto_restante = (self.monto_total + total_ingresos) - total_gastos
        self.save()

    def porcentaje_gastado(self):
        """Calcula el porcentaje gastado del presupuesto (excluye gastos con tarjeta diferida)."""
        total_gastos = self.gastos.exclude(metodo_pago='tarjeta').aggregate(total=models.Sum('monto'))['total'] or 0
        total_ingresos = self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
        if self.tipo == 'abierto':
            if total_ingresos == 0:
                return 0
            porcentaje = (total_gastos / total_ingresos) * 100
        else:
            monto_total_con_ingresos = self.monto_total + total_ingresos
            if monto_total_con_ingresos == 0:
                return 0
            porcentaje = (total_gastos / monto_total_con_ingresos) * 100
            
        return min(max(porcentaje, 0), 100)
        
    @property
    def total_ingresos(self):
        """Devuelve la suma total de todos los ingresos del presupuesto."""
        return self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0

    @property
    def total_gastos_computables(self):
        """Devuelve los gastos que descuentan el presupuesto (Efectivo y Transferencia)."""
        return self.gastos.exclude(metodo_pago='tarjeta').aggregate(total=models.Sum('monto'))['total'] or 0

    @property
    def total_tarjeta(self):
        """Devuelve el total acumulado de gastos con tarjeta (a pagar el mes siguiente)."""
        return self.gastos.filter(metodo_pago='tarjeta').aggregate(total=models.Sum('monto'))['total'] or 0

    @property
    def saldo_efectivo(self):
        """Saldo neto disponible en efectivo (Ingresos efectivo - Gastos efectivo)."""
        ing = self.ingresos.filter(tipo_ingreso='efectivo').aggregate(total=models.Sum('monto'))['total'] or 0
        gas = self.gastos.filter(metodo_pago='efectivo').aggregate(total=models.Sum('monto'))['total'] or 0
        return ing - gas

    @property
    def saldo_transferencia(self):
        """Saldo neto disponible en banco/transferencia (Transferencias + Sueldos - Gastos transferencia)."""
        ing = self.ingresos.filter(tipo_ingreso__in=['transferencia', 'sueldo']).aggregate(total=models.Sum('monto'))['total'] or 0
        gas = self.gastos.filter(metodo_pago='transferencia').aggregate(total=models.Sum('monto'))['total'] or 0
        return ing - gas

    @property
    def total_sueldo(self):
        """Total ingresado bajo concepto de sueldo."""
        return self.ingresos.filter(tipo_ingreso='sueldo').aggregate(total=models.Sum('monto'))['total'] or 0
        
    def monto_total_con_ingresos(self):
        """Devuelve el monto total disponible antes de egresos."""
        if self.tipo == 'abierto':
            return self.total_ingresos
        return self.monto_total + self.total_ingresos

    def puede_ver(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.usuario_id == user.id or self.compartidos.filter(usuario=user).exists()

    def puede_editar(self, user):
        if not user or not user.is_authenticated:
            return False
        return self.usuario_id == user.id or self.compartidos.filter(usuario=user, permiso='editar').exists()


class PresupuestoCompartido(models.Model):
    PERMISOS = [
        ('ver', 'Solo lectura'),
        ('editar', 'Puede editar'),
    ]

    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='compartidos')
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='presupuestos_compartidos')
    permiso = models.CharField(max_length=10, choices=PERMISOS, default='ver')
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('presupuesto', 'usuario')

    def __str__(self):
        return f'{self.presupuesto} compartido con {self.usuario} ({self.permiso})'


class CuentaBancaria(models.Model):
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cuentas_bancarias')
    nombre = models.CharField(max_length=60)
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = ('usuario', 'nombre')
        verbose_name = 'Cuenta Bancaria / Billetera'
        verbose_name_plural = 'Cuentas Bancarias / Billeteras'
        ordering = ['nombre']

    def __str__(self):
        return self.nombre


class Gasto(models.Model):
    METODOS_PAGO = [
        ('efectivo', 'Efectivo'),
        ('transferencia', 'Transferencia'),
        ('tarjeta', 'Tarjeta'),
    ]
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='gastos')
    categoria = models.ForeignKey(Categoria, on_delete=models.PROTECT, null=True, blank=True)
    nombre = models.CharField(max_length=100)
    persona = models.CharField(max_length=60, blank=True, default='')
    cuenta_bancaria = models.ForeignKey(CuentaBancaria, on_delete=models.SET_NULL, null=True, blank=True, related_name='gastos')
    descripcion = models.TextField(blank=True, null=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    metodo_pago = models.CharField(max_length=20, choices=METODOS_PAGO, default='efectivo')
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        if not self.pk and not self.fecha:
            self.fecha = timezone.localtime(timezone.now())
        if timezone.is_aware(self.fecha):
            self.fecha = timezone.localtime(self.fecha).replace(tzinfo=None)
            
        super().save(*args, **kwargs)
        if self.presupuesto:
            self.presupuesto.actualizar_monto_restante()

    def delete(self, *args, **kwargs):
        presupuesto = self.presupuesto
        super().delete(*args, **kwargs)
        if presupuesto:
            presupuesto.actualizar_monto_restante()

    def __str__(self):
        return f"{self.nombre} - ${self.monto} ({self.get_metodo_pago_display()})"


class Ingreso(models.Model):
    TIPOS_INGRESO = [
        ('transferencia', 'Transferencia'),
        ('efectivo', 'Efectivo'),
        ('sueldo', 'Sueldo'),
    ]
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='ingresos')
    cuenta_bancaria = models.ForeignKey(CuentaBancaria, on_delete=models.SET_NULL, null=True, blank=True, related_name='ingresos')
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    tipo_ingreso = models.CharField(max_length=20, choices=TIPOS_INGRESO, default='transferencia')
    fecha = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        if not self.pk and not self.fecha:
            self.fecha = timezone.localtime(timezone.now())
        if timezone.is_aware(self.fecha):
            self.fecha = timezone.localtime(self.fecha).replace(tzinfo=None)
            
        super().save(*args, **kwargs)
        if self.presupuesto:
            self.presupuesto.actualizar_monto_restante()

    def delete(self, *args, **kwargs):
        presupuesto = self.presupuesto
        super().delete(*args, **kwargs)
        if presupuesto:
            presupuesto.actualizar_monto_restante()

    def __str__(self):
        return f"{self.nombre} - ${self.monto} ({self.get_tipo_ingreso_display()})"
