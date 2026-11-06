from decimal import Decimal
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
        ('prestamo', 'Control de Préstamo (Flujo abierto)'),
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
    tasa_interes_prestamo = models.DecimalField(max_digits=5, decimal_places=2, default=4.50, verbose_name="Tasa de interés de la app (%)")
    aporte_mensual_prestamo = models.DecimalField(max_digits=12, decimal_places=2, default=600000.00, verbose_name="Aporte propio mensual")
    deuda_inicial_prestamo = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, blank=True, verbose_name="Deuda total inicial (opcional)")

    def __str__(self):
        return f"{self.nombre} - {self.fecha_inicio} a {self.fecha_fin}"

    def actualizar_monto_restante(self):
        # Gastos que descuentan ahora (excluye tarjeta que impactará el mes siguiente)
        total_gastos = self.gastos.exclude(metodo_pago='tarjeta').aggregate(total=models.Sum('monto'))['total'] or 0
        total_ingresos = self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
        if self.tipo in ['abierto', 'prestamo']:
            self.monto_restante = total_ingresos - total_gastos
        else:
            self.monto_restante = (self.monto_total + total_ingresos) - total_gastos
        self.save()

    def porcentaje_gastado(self):
        """Calcula el porcentaje gastado del presupuesto (excluye gastos con tarjeta diferida)."""
        total_gastos = self.gastos.exclude(metodo_pago='tarjeta').aggregate(total=models.Sum('monto'))['total'] or 0
        total_ingresos = self.ingresos.aggregate(total=models.Sum('monto'))['total'] or 0
        
        if self.tipo in ['abierto', 'prestamo']:
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
        if self.tipo in ['abierto', 'prestamo']:
            return self.total_ingresos
        return self.monto_total + self.total_ingresos

    def proyeccion_prestamo(self):
        """Calcula el cronograma de amortización del préstamo mes a mes con tarjeta al 4.5%."""
        if self.tipo != 'prestamo':
            return None
        
        # Obtener deuda base del ciclo activo o extracciones
        ciclo_activo = self.ciclos_prestamo.filter(esta_cerrado=False).order_by('-fecha_inicio').first()
        deuda = 0.0
        if ciclo_activo:
            deuda_prox = float(ciclo_activo.deuda_proximo_ciclo())
            if deuda_prox > 0:
                deuda = deuda_prox
            elif ciclo_activo.deuda_a_devolver > 0:
                deuda = float(ciclo_activo.deuda_a_devolver)

        if deuda <= 0:
            extracciones = self.ingresos.filter(es_extraccion_tarjeta=True).order_by('-fecha')
            if extracciones.exists():
                ult_fecha = extracciones.first().fecha
                extracciones_ultimo_mes = [
                    e for e in extracciones 
                    if e.fecha.year == ult_fecha.year and e.fecha.month == ult_fecha.month
                ]
                tasa_factor = 1.0 + (float(self.tasa_interes_prestamo or 4.50) / 100.0)
                suma_vence_proximo = sum(
                    float(e.monto_proximo_mes if e.monto_proximo_mes else (float(e.monto) * tasa_factor))
                    for e in extracciones_ultimo_mes
                )
                deuda = suma_vence_proximo
        
        if deuda <= 0 and self.deuda_inicial_prestamo:
            deuda = float(self.deuda_inicial_prestamo)
            
        aporte = float(self.aporte_mensual_prestamo) if self.aporte_mensual_prestamo else 600000.0
        tasa = float(self.tasa_interes_prestamo or 4.50) / 100.0
        
        if deuda <= 0:
            return {
                'cronograma': [],
                'total_meses': 0,
                'meses_totales': 0,
                'total_intereses': 0.0,
                'deuda_actual': 0.0,
                'proximo_a_pagar': 0.0,
            }
        
        cronograma = []
        mes = 0
        total_intereses = 0.0
        deuda_inicial_base = deuda
        
        while deuda > 0 and mes < 60:
            mes += 1
            saca = max(0.0, deuda - aporte)
            if saca <= 0:
                cronograma.append({
                    'mes': mes,
                    'deuda_inicio': round(deuda, 2),
                    'aporte': round(deuda, 2),
                    'saca_tarjeta': 0.0,
                    'interes': 0.0,
                    'vence_proximo': 0.0,
                    'deuda_fin': 0.0,
                    'es_ultimo': True
                })
                break
            interes = saca * tasa
            total_intereses += interes
            deuda_sig = saca + interes
            cronograma.append({
                'mes': mes,
                'deuda_inicio': round(deuda, 2),
                'aporte': round(aporte, 2),
                'saca_tarjeta': round(saca, 2),
                'interes': round(interes, 2),
                'vence_proximo': round(deuda_sig, 2),
                'deuda_fin': round(deuda_sig, 2),
                'es_ultimo': False
            })
            deuda = deuda_sig
            
        return {
            'cronograma': cronograma,
            'total_meses': mes,
            'meses_totales': mes,
            'total_intereses': round(total_intereses, 2),
            'deuda_actual': round(deuda_inicial_base, 2),
            'proximo_a_pagar': round(cronograma[0]['vence_proximo'] if cronograma else 0.0, 2),
        }

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
    es_rapido = models.BooleanField(default=False, verbose_name="Carga rápida pendiente")

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        if not self.pk and not self.fecha:
            self.fecha = timezone.now()
        elif self.fecha and timezone.is_naive(self.fecha):
            self.fecha = timezone.make_aware(self.fecha, timezone.get_current_timezone())
            
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


class CicloPrestamo(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='ciclos_prestamo')
    nombre = models.CharField(max_length=100)
    fecha_inicio = models.DateField(default=timezone.now)
    fecha_fin = models.DateField(null=True, blank=True)
    deuda_a_devolver = models.DecimalField(max_digits=12, decimal_places=2, default=0.00, verbose_name="Deuda que vence en este período")
    esta_cerrado = models.BooleanField(default=False, verbose_name="Período cerrado")
    fecha_cierre = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_inicio', '-id']
        verbose_name = 'Ciclo de Préstamo'
        verbose_name_plural = 'Ciclos de Préstamo'

    def __str__(self):
        return f"{self.nombre} ({'Cerrado' if self.esta_cerrado else 'Activo'})"

    def total_tarjetas(self):
        return self.ingresos.filter(es_extraccion_tarjeta=True).aggregate(t=models.Sum('monto'))['t'] or Decimal('0')

    def total_interes_tarjetas(self):
        return sum(i.interes_monto for i in self.ingresos.filter(es_extraccion_tarjeta=True)) or Decimal('0')

    def deuda_proximo_ciclo(self):
        tasa_factor = Decimal('1') + (self.presupuesto.tasa_interes_prestamo / Decimal('100'))
        return sum((i.monto_proximo_mes or round(i.monto * tasa_factor, 2)) for i in self.ingresos.filter(es_extraccion_tarjeta=True)) or Decimal('0')

    def total_efectivo(self):
        return self.ingresos.filter(es_aporte_capital=True).aggregate(t=models.Sum('monto'))['t'] or Decimal('0')

    def total_devuelto(self):
        return self.total_tarjetas() + self.total_efectivo()

    def pendiente_devolver(self):
        return max(Decimal('0'), self.deuda_a_devolver - self.total_devuelto())

    def porcentaje_cubierto(self):
        if self.deuda_a_devolver > 0:
            return min(100, round((self.total_devuelto() / self.deuda_a_devolver) * 100))
        return 100 if self.total_devuelto() > 0 else 0


class TarjetaPrestamo(models.Model):
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='tarjetas_prestamo')
    nombre = models.CharField(max_length=100)
    dia_cierre_habitual = models.PositiveSmallIntegerField(default=21, verbose_name="Día de cierre habitual")
    dia_vencimiento_habitual = models.PositiveSmallIntegerField(default=5, verbose_name="Día de vencimiento habitual")
    proxima_fecha_cierre = models.DateField(null=True, blank=True, verbose_name="Próxima fecha exacta de cierre")
    proxima_fecha_vencimiento = models.DateField(null=True, blank=True, verbose_name="Próxima fecha de vencimiento")
    nota = models.CharField(max_length=200, blank=True, null=True)

    class Meta:
        ordering = ['dia_cierre_habitual', 'nombre']
        verbose_name = 'Tarjeta del Préstamo'
        verbose_name_plural = 'Tarjetas del Préstamo'

    def __str__(self):
        return self.nombre

    def info_cierre(self, hoy=None):
        if hoy is None:
            hoy = timezone.localdate()
        cierre = self.proxima_fecha_cierre
        if not cierre:
            try:
                cierre = hoy.replace(day=min(self.dia_cierre_habitual, 28))
            except ValueError:
                cierre = hoy

        vence = self.proxima_fecha_vencimiento
        if not vence:
            try:
                mes_vence = hoy.month + 1 if self.dia_vencimiento_habitual <= self.dia_cierre_habitual else hoy.month
                year_vence = hoy.year + (1 if mes_vence > 12 else 0)
                mes_vence = 1 if mes_vence > 12 else mes_vence
                vence = hoy.replace(year=year_vence, month=mes_vence, day=min(self.dia_vencimiento_habitual, 28))
            except ValueError:
                vence = hoy

        ya_cerro = (hoy > cierre)
        dias_para_cierre = (cierre - hoy).days if not ya_cerro else 0
        dias_pasados = (hoy - cierre).days if ya_cerro else 0

        return {
            'ya_cerro': ya_cerro,
            'fecha_cierre': cierre,
            'fecha_vencimiento': vence,
            'dias_para_cierre': dias_para_cierre,
            'dias_pasados': dias_pasados,
            'es_seguro_sacar': ya_cerro,
            'mensaje': "Habilitada para sacar (diferido)" if ya_cerro else f"Cierra el {cierre.strftime('%d/%m')} (en {dias_para_cierre} días)"
        }


class Ingreso(models.Model):
    TIPOS_INGRESO = [
        ('transferencia', 'Transferencia'),
        ('efectivo', 'Efectivo'),
        ('sueldo', 'Sueldo'),
    ]
    presupuesto = models.ForeignKey(Presupuesto, on_delete=models.CASCADE, related_name='ingresos')
    ciclo_prestamo = models.ForeignKey(CicloPrestamo, null=True, blank=True, on_delete=models.SET_NULL, related_name='ingresos')
    tarjeta_prestamo = models.ForeignKey(TarjetaPrestamo, null=True, blank=True, on_delete=models.SET_NULL, related_name='extracciones')
    cuenta_bancaria = models.ForeignKey(CuentaBancaria, on_delete=models.SET_NULL, null=True, blank=True, related_name='ingresos')
    nombre = models.CharField(max_length=100)
    descripcion = models.TextField(blank=True, null=True)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    tipo_ingreso = models.CharField(max_length=20, choices=TIPOS_INGRESO, default='transferencia')
    fecha = models.DateTimeField(default=timezone.now)
    es_rapido = models.BooleanField(default=False, verbose_name="Carga rápida pendiente")
    monto_proximo_mes = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True, verbose_name="Monto a pagar próximo mes (con interés)")
    tasa_interes = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True, verbose_name="Tasa de interés aplicada (%)")
    es_extraccion_tarjeta = models.BooleanField(default=False, verbose_name="Extracción con tarjeta para préstamo")
    es_aporte_capital = models.BooleanField(default=False, verbose_name="Aporte propio para amortizar deuda")

    @property
    def interes_monto(self):
        if self.monto_proximo_mes and self.monto and self.monto_proximo_mes > self.monto:
            return self.monto_proximo_mes - self.monto
        if self.tasa_interes and self.monto and self.es_extraccion_tarjeta:
            return (self.monto * self.tasa_interes) / 100
        return 0

    def clean(self):
        super().clean()
        if self.monto is not None and self.monto < 0:
            raise ValidationError({'monto': 'El monto debe ser un número positivo'})

    def save(self, *args, **kwargs):
        if not self.pk and not self.fecha:
            self.fecha = timezone.now()
        elif self.fecha and timezone.is_naive(self.fecha):
            self.fecha = timezone.make_aware(self.fecha, timezone.get_current_timezone())
            
        if self.presupuesto and self.presupuesto.tipo == 'prestamo' and not self.ciclo_prestamo:
            ciclo = self.presupuesto.ciclos_prestamo.filter(esta_cerrado=False).order_by('-fecha_inicio').first()
            if not ciclo:
                nombre_ciclo = f"Período {self.fecha.strftime('%B %Y').capitalize()}"
                ciclo = CicloPrestamo.objects.create(
                    presupuesto=self.presupuesto,
                    nombre=nombre_ciclo,
                    fecha_inicio=self.fecha.date(),
                    deuda_a_devolver=self.presupuesto.deuda_inicial_prestamo or Decimal('0.00'),
                    esta_cerrado=False
                )
            self.ciclo_prestamo = ciclo

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
