from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.http import HttpResponseForbidden
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.db import models
from django.db.models import Q
from django.core.exceptions import ValidationError
from django.utils import timezone
from itertools import groupby
from decimal import Decimal, InvalidOperation
from datetime import datetime, date, time, timedelta
import re
from core.auth import asignar_presupuestos_sin_usuario
from .models import Presupuesto, PresupuestoCompartido, Categoria, Gasto, Ingreso, CuentaBancaria, CicloPrestamo, TarjetaPrestamo, DiferenciaTarjeta
from .forms import PresupuestoForm, CompartirPresupuestoForm, CategoriaForm, GastoForm, IngresoForm, TarjetaPrestamoForm, CerrarCicloPrestamoForm, DiferenciaTarjetaForm


def presupuestos_visibles(user):
    asignar_presupuestos_sin_usuario()
    return Presupuesto.objects.filter(Q(usuario=user) | Q(compartidos__usuario=user)).distinct()


def presupuestos_editables(user):
    asignar_presupuestos_sin_usuario()
    return Presupuesto.objects.filter(Q(usuario=user) | Q(compartidos__usuario=user, compartidos__permiso='editar')).distinct()


def get_user_recent_personas(user):
    """Retorna los tags/personas únicos ordenados por los últimos usados (más recientes primero)."""
    raw = (
        Gasto.objects.filter(presupuesto__usuario=user)
        .exclude(persona__isnull=True)
        .exclude(persona='')
        .order_by('-fecha', '-id')
        .values_list('persona', flat=True)
    )
    result = []
    for p in raw:
        clean = p.strip()
        if clean and clean not in result:
            result.append(clean)
    return result


def get_user_recent_cuentas(user):
    """Retorna las cuentas bancarias únicas ordenadas por últimas usadas o registradas."""
    raw = (
        CuentaBancaria.objects.filter(usuario=user)
        .order_by('-id')
        .values_list('nombre', flat=True)
    )
    result = []
    for c in raw:
        clean = c.strip()
        if clean and clean not in result:
            result.append(clean)
    return result

class PresupuestoUsuarioMixin(LoginRequiredMixin):
    def get_queryset(self):
        return presupuestos_visibles(self.request.user)


class GastoUsuarioMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Gasto.objects.filter(presupuesto__in=presupuestos_visibles(self.request.user))


class GastoEditableMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Gasto.objects.filter(presupuesto__in=presupuestos_editables(self.request.user))


class IngresoUsuarioMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Ingreso.objects.filter(presupuesto__in=presupuestos_visibles(self.request.user))


class IngresoEditableMixin(LoginRequiredMixin):
    def get_queryset(self):
        return Ingreso.objects.filter(presupuesto__in=presupuestos_editables(self.request.user))


# Vistas de Presupuesto
@login_required
def presupuestos_list(request):
    presupuestos = presupuestos_visibles(request.user).order_by('-fecha_creacion')
    return render(request, 'presupuestos/index.html', {'presupuestos': presupuestos})

class PresupuestoDetailView(PresupuestoUsuarioMixin, DetailView):
    model = Presupuesto
    template_name = 'presupuestos/ver_presupuesto.html'
    context_object_name = 'presupuesto'

    def _fecha_local(self, transaccion):
        fecha = getattr(transaccion, 'fecha', None)
        if not fecha:
            return timezone.localtime(timezone.now())
        if timezone.is_naive(fecha):
            fecha = timezone.make_aware(fecha, timezone.get_current_timezone())
        return timezone.localtime(fecha)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Obtener gastos e ingresos ordenados
        gastos = list(self.object.gastos.select_related('categoria', 'cuenta_bancaria').order_by('-fecha'))
        ingresos = list(self.object.ingresos.select_related('cuenta_bancaria').order_by('-fecha'))
        
        # Calcular totales
        total_gastos = sum(gasto.monto for gasto in gastos)
        total_gastos_computables = sum(gasto.monto for gasto in gastos if gasto.metodo_pago != 'tarjeta')
        total_tarjeta = sum(gasto.monto for gasto in gastos if gasto.metodo_pago == 'tarjeta')
        total_ingresos = sum(ingreso.monto for ingreso in ingresos)

        # Desglose de saldos por medio de pago
        ingresos_efectivo = sum(i.monto for i in ingresos if i.tipo_ingreso == 'efectivo')
        gastos_efectivo = sum(g.monto for g in gastos if g.metodo_pago == 'efectivo')
        saldo_efectivo = ingresos_efectivo - gastos_efectivo

        ingresos_transferencia = sum(i.monto for i in ingresos if i.tipo_ingreso in ['transferencia', 'sueldo'])
        gastos_transferencia = sum(g.monto for g in gastos if g.metodo_pago == 'transferencia')
        saldo_transferencia = ingresos_transferencia - gastos_transferencia
        total_sueldo = sum(i.monto for i in ingresos if i.tipo_ingreso == 'sueldo')

        owner = self.object.usuario
        user_cuentas = list(CuentaBancaria.objects.filter(usuario=owner).order_by('nombre'))

        # Desglose de saldos por cuenta bancaria / billetera
        cuentas_map = {}
        for i in ingresos:
            if i.cuenta_bancaria:
                c_nom = i.cuenta_bancaria.nombre
                if c_nom not in cuentas_map:
                    cuentas_map[c_nom] = {'nombre': c_nom, 'ingresos': Decimal('0'), 'gastos': Decimal('0'), 'saldo': Decimal('0')}
                cuentas_map[c_nom]['ingresos'] += i.monto
        for g in gastos:
            if g.cuenta_bancaria:
                c_nom = g.cuenta_bancaria.nombre
                if c_nom not in cuentas_map:
                    cuentas_map[c_nom] = {'nombre': c_nom, 'ingresos': Decimal('0'), 'gastos': Decimal('0'), 'saldo': Decimal('0')}
                cuentas_map[c_nom]['gastos'] += g.monto

        for c in cuentas_map.values():
            c['saldo'] = c['ingresos'] - c['gastos']

        # Filtrar solo cuentas y billeteras con saldo diferente de cero
        saldos_por_cuenta = [c for c in sorted(cuentas_map.values(), key=lambda x: -x['saldo']) if c['saldo'] != Decimal('0')]

        # Desglose de gastos por persona / destinatario
        personas_map = {}
        for g in gastos:
            p_nom = g.persona.strip() if g.persona else 'Sin asignar'
            if p_nom not in personas_map:
                personas_map[p_nom] = {'persona': p_nom, 'total': Decimal('0'), 'cantidad': 0}
            personas_map[p_nom]['total'] += g.monto
            personas_map[p_nom]['cantidad'] += 1

        resumen_gastos_por_persona = sorted(personas_map.values(), key=lambda x: -x['total'])
        for item in resumen_gastos_por_persona:
            item['porcentaje'] = round((item['total'] / total_gastos) * 100) if total_gastos else 0

        # Personas en este presupuesto y todas las personas del usuario
        personas_list = sorted(list({g.persona.strip() for g in gastos if g.persona and g.persona.strip()}))
        todas_las_personas = sorted(list({
            p.strip()
            for p in Gasto.objects.filter(presupuesto__usuario=owner).exclude(persona='').values_list('persona', flat=True)
            if p.strip()
        }))
        if not personas_list:
            personas_list = todas_las_personas

        gastos_por_tipo = {}
        for gasto in gastos:
            tipo = gasto.categoria.nombre if gasto.categoria else 'Sin categoría'
            if tipo not in gastos_por_tipo:
                gastos_por_tipo[tipo] = {'tipo': tipo, 'total': Decimal('0'), 'cantidad': 0}
            gastos_por_tipo[tipo]['total'] += gasto.monto
            gastos_por_tipo[tipo]['cantidad'] += 1

        resumen_gastos_por_tipo = sorted(
            gastos_por_tipo.values(),
            key=lambda item: (-item['total'], item['tipo'].lower()),
        )
        for item in resumen_gastos_por_tipo:
            item['porcentaje'] = round((item['total'] / total_gastos) * 100) if total_gastos else 0

        transacciones = ingresos + gastos
        for transaccion in transacciones:
            transaccion.fecha_local = self._fecha_local(transaccion)
        transacciones.sort(key=lambda transaccion: transaccion.fecha_local, reverse=True)
        transacciones_por_dia = [
            {'grouper': fecha, 'list': list(items)}
            for fecha, items in groupby(transacciones, key=lambda transaccion: transaccion.fecha_local.date())
        ]
        
        monto_total_con_ingresos = (
            total_ingresos if self.object.tipo in ['abierto', 'prestamo'] else (self.object.monto_total + total_ingresos)
        )
        saldo_restante = monto_total_con_ingresos - total_gastos_computables

        # Agregar al contexto
        context['gastos'] = gastos
        context['ingresos'] = ingresos
        context['transacciones_por_dia'] = transacciones_por_dia
        context['total_gastos'] = total_gastos
        context['total_gastos_computables'] = total_gastos_computables
        context['total_tarjeta'] = total_tarjeta
        context['saldo_efectivo'] = saldo_efectivo
        context['saldo_transferencia'] = saldo_transferencia
        context['total_sueldo'] = total_sueldo
        context['saldo_restante'] = saldo_restante
        context['total_ingresos'] = total_ingresos
        context['resumen_gastos_por_tipo'] = resumen_gastos_por_tipo
        context['resumen_gastos_por_persona'] = resumen_gastos_por_persona
        context['saldos_por_cuenta'] = saldos_por_cuenta
        context['personas_list'] = personas_list
        context['todas_las_personas'] = todas_las_personas
        context['monto_total_con_ingresos'] = monto_total_con_ingresos
        context['puede_editar'] = self.object.puede_editar(self.request.user)
        context['es_duenio'] = self.object.usuario_id == self.request.user.id
        context['compartir_form'] = CompartirPresupuestoForm(presupuesto=self.object)
        context['usuarios_compartidos'] = self.object.compartidos.select_related('usuario').order_by('usuario__username')
        
        # Para depuración
        context['debug_gastos_count'] = len(gastos)
        context['debug_ingresos_count'] = len(ingresos)

        if self.object.tipo == 'prestamo':
            # 1. Sembrado automático de tarjetas si no existen
            if not self.object.tarjetas_prestamo.exists():
                TarjetaPrestamo.objects.bulk_create([
                    TarjetaPrestamo(
                        presupuesto=self.object,
                        nombre="Patagonia Rubén",
                        dia_cierre_habitual=21,
                        proxima_fecha_cierre=date(2026, 11, 19),
                        dia_vencimiento_habitual=5,
                        nota="Vence del 1 al 5"
                    ),
                    TarjetaPrestamo(
                        presupuesto=self.object,
                        nombre="Patagonia Palmira",
                        dia_cierre_habitual=22,
                        proxima_fecha_cierre=date(2026, 11, 19),
                        dia_vencimiento_habitual=5,
                        nota="Vence del 1 al 5"
                    ),
                    TarjetaPrestamo(
                        presupuesto=self.object,
                        nombre="Naranja",
                        dia_cierre_habitual=27,
                        proxima_fecha_cierre=date(2026, 11, 27),
                        dia_vencimiento_habitual=10,
                        nota="Vence el 10"
                    ),
                ])

            # 2. Inicializar ciclo activo si no existe
            if not self.object.ciclos_prestamo.exists():
                ciclo_inicial = CicloPrestamo.objects.create(
                    presupuesto=self.object,
                    nombre="Período Noviembre 2026",
                    fecha_inicio=date(2026, 10, 21),
                    deuda_a_devolver=self.object.deuda_inicial_prestamo or Decimal('10129746.00'),
                    esta_cerrado=False
                )
                self.object.ingresos.filter(ciclo_prestamo__isnull=True).update(ciclo_prestamo=ciclo_inicial)

            ciclos = self.object.ciclos_prestamo.all()
            ciclo_activo = ciclos.filter(esta_cerrado=False).first()
            
            # Selector de ciclo (o por defecto el activo)
            ciclo_id = self.request.GET.get('ciclo_id')
            if ciclo_id:
                ciclo_seleccionado = ciclos.filter(pk=ciclo_id).first() or ciclo_activo
            else:
                ciclo_seleccionado = ciclo_activo or ciclos.first()

            # Asegurar que ingresos huérfanos se vinculen al ciclo activo
            if ciclo_activo:
                self.object.ingresos.filter(ciclo_prestamo__isnull=True).update(ciclo_prestamo=ciclo_activo)

            # Información de las tarjetas y cierres
            tarjetas_info = []
            for t in self.object.tarjetas_prestamo.all():
                tarjetas_info.append({
                    'tarjeta': t,
                    'info': t.info_cierre()
                })

            if ciclo_seleccionado:
                deuda_base_este_mes = ciclo_seleccionado.deuda_a_devolver
                total_diferencias_este_mes = ciclo_seleccionado.total_diferencias()
                deuda_que_vence_este_mes = ciclo_seleccionado.deuda_total_a_devolver()
                tarjetas_actuales = ciclo_seleccionado.ingresos.filter(es_extraccion_tarjeta=True)
                aportes_actuales = ciclo_seleccionado.ingresos.filter(es_aporte_capital=True)
                total_extraido_tarjetas = ciclo_seleccionado.total_tarjetas()
                total_interes_tarjetas = ciclo_seleccionado.total_interes_tarjetas()
                deuda_total_proximo_mes = ciclo_seleccionado.deuda_proximo_ciclo()
                total_aportes_efectivo = ciclo_seleccionado.total_efectivo()
                total_devuelto_este_mes = ciclo_seleccionado.total_devuelto()
                pendiente_devolucion_este_mes = ciclo_seleccionado.pendiente_devolver()
                porcentaje_cubierto = ciclo_seleccionado.porcentaje_cubierto()
                diferencias_actuales = ciclo_seleccionado.diferencias_tarjetas.select_related('tarjeta').all()
                resumen_diferencias_tarjetas = ciclo_seleccionado.resumen_diferencias_por_tarjeta()

                # Filtrar transacciones visibles por el ciclo seleccionado
                ingresos_ciclo = list(ciclo_seleccionado.ingresos.select_related('cuenta_bancaria', 'tarjeta_prestamo').order_by('-fecha'))
                for item in ingresos_ciclo:
                    item.fecha_local = self._fecha_local(item)
                ingresos_ciclo.sort(key=lambda x: x.fecha_local, reverse=True)
                transacciones_por_dia = [
                    {'grouper': fecha, 'list': list(items)}
                    for fecha, items in groupby(ingresos_ciclo, key=lambda x: x.fecha_local.date())
                ]
                context['transacciones_por_dia'] = transacciones_por_dia
                context['debug_ingresos_count'] = len(ingresos_ciclo)
                context['debug_gastos_count'] = 0
            else:
                deuda_base_este_mes = Decimal('0')
                total_diferencias_este_mes = Decimal('0')
                deuda_que_vence_este_mes = Decimal('0')
                tarjetas_actuales = []
                aportes_actuales = []
                total_extraido_tarjetas = Decimal('0')
                total_interes_tarjetas = Decimal('0')
                deuda_total_proximo_mes = Decimal('0')
                total_aportes_efectivo = Decimal('0')
                total_devuelto_este_mes = Decimal('0')
                pendiente_devolucion_este_mes = Decimal('0')
                porcentaje_cubierto = 0
                diferencias_actuales = []
                resumen_diferencias_tarjetas = []

            proyeccion = self.object.proyeccion_prestamo()
            aporte_habitual = self.object.aporte_mensual_prestamo or Decimal('600000.00')
            tarjeta_necesaria_proximo_mes = max(Decimal('0'), deuda_total_proximo_mes - aporte_habitual)

            context['proyeccion_prestamo'] = proyeccion
            context['ciclos_prestamo'] = ciclos
            context['ciclo_actual'] = ciclo_seleccionado
            context['ciclo_activo'] = ciclo_activo
            context['tarjetas_info'] = tarjetas_info
            context['tarjetas_actuales'] = tarjetas_actuales
            context['aportes_actuales'] = aportes_actuales
            context['total_extraido_tarjeta'] = total_extraido_tarjetas
            context['total_interes_acumulado'] = total_interes_tarjetas
            context['total_aportes_propios'] = total_aportes_efectivo
            context['deuda_total_proximo_mes'] = deuda_total_proximo_mes
            context['deuda_base_este_mes'] = deuda_base_este_mes
            context['total_diferencias_este_mes'] = total_diferencias_este_mes
            context['deuda_que_vence_este_mes'] = deuda_que_vence_este_mes
            context['diferencias_actuales'] = diferencias_actuales
            context['resumen_diferencias_tarjetas'] = resumen_diferencias_tarjetas
            context['total_devuelto_este_mes'] = total_devuelto_este_mes
            context['pendiente_devolucion_este_mes'] = pendiente_devolucion_este_mes
            context['porcentaje_cubierto'] = porcentaje_cubierto
            context['aporte_habitual'] = aporte_habitual
            context['tarjeta_necesaria_proximo_mes'] = tarjeta_necesaria_proximo_mes
            context['proximo_a_pagar'] = deuda_total_proximo_mes if deuda_total_proximo_mes > 0 else deuda_que_vence_este_mes
            context['deuda_actual'] = deuda_total_proximo_mes

            # Forms de apoyo
            context['form_tarjeta'] = TarjetaPrestamoForm()
            context['form_diferencia'] = DiferenciaTarjetaForm(presupuesto=self.object)
            context['form_cerrar_ciclo'] = CerrarCicloPrestamoForm(initial={
                'nuevo_nombre': "Período Diciembre 2026 (desde 20/11)",
                'nueva_fecha_inicio': date(2026, 11, 20),
                'deuda_a_devolver': deuda_total_proximo_mes
            })
        
        return context

class PresupuestoCreateView(LoginRequiredMixin, CreateView):
    model = Presupuesto
    form_class = PresupuestoForm
    template_name = 'presupuestos/presupuesto_form.html'
    success_url = reverse_lazy('presupuestos:index')

    def form_valid(self, form):
        form.instance.usuario = self.request.user
        messages.success(self.request, 'Presupuesto creado exitosamente')
        return super().form_valid(form)

class PresupuestoUpdateView(PresupuestoUsuarioMixin, UpdateView):
    model = Presupuesto
    form_class = PresupuestoForm
    template_name = 'presupuestos/presupuesto_form.html'
    success_url = reverse_lazy('presupuestos:index')

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.usuario_id != request.user.id:
            return HttpResponseForbidden('Solo el dueño puede modificar el presupuesto.')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        # Guardar el objeto para tener acceso a los datos anteriores
        self.object = form.save(commit=False)
        
        # Si el monto total ha cambiado, actualizar el monto restante
        if 'monto_total' in form.changed_data:
            # Guardar primero para que el objeto tenga el nuevo monto_total
            self.object.save()
            # Actualizar el monto restante basado en los gastos actuales
            self.object.actualizar_monto_restante()
        
        messages.success(self.request, 'Presupuesto actualizado exitosamente')
        return super().form_valid(form)

class PresupuestoDeleteView(PresupuestoUsuarioMixin, DeleteView):
    model = Presupuesto
    template_name = 'presupuestos/presupuesto_confirm_delete.html'
    success_url = reverse_lazy('presupuestos:index')

    def dispatch(self, request, *args, **kwargs):
        self.object = self.get_object()
        if self.object.usuario_id != request.user.id:
            return HttpResponseForbidden('Solo el dueño puede eliminar el presupuesto.')
        return super().dispatch(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Presupuesto eliminado exitosamente')
        return super().delete(request, *args, **kwargs)

# Vistas de Categoría
class CategoriaCreateView(LoginRequiredMixin, CreateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'presupuestos/categoria_form.html'
    success_url = reverse_lazy('presupuestos:listar_categorias')

    def get_success_url(self):
        # Si se está creando desde el formulario de gastos, volver allí
        presupuesto_pk = self.request.GET.get('presupuesto_pk')
        if presupuesto_pk:
            return reverse_lazy('presupuestos:crear_gasto', kwargs={'presupuesto_pk': presupuesto_pk})
        return super().get_success_url()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        # Agregar el parámetro next y presupuesto_pk al contexto para usarlo en el template
        context['next_url'] = self.request.GET.get('next', 'presupuestos:index')
        context['presupuesto_pk'] = self.request.GET.get('presupuesto_pk')
        return context

class CategoriaUpdateView(LoginRequiredMixin, UpdateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'presupuestos/categoria_form.html'
    success_url = reverse_lazy('presupuestos:listar_categorias')

    def form_valid(self, form):
        messages.success(self.request, 'Categoría actualizada exitosamente')
        return super().form_valid(form)

class CategoriaDeleteView(LoginRequiredMixin, DeleteView):
    model = Categoria
    template_name = 'presupuestos/categoria_confirm_delete.html'
    success_url = reverse_lazy('presupuestos:listar_categorias')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Categoría eliminada exitosamente')
        return super().delete(request, *args, **kwargs)

class CategoriaListView(LoginRequiredMixin, ListView):
    model = Categoria
    template_name = 'presupuestos/categorias.html'
    context_object_name = 'categorias'
    ordering = ['nombre']

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['categorias'] = Categoria.objects.annotate(
            gastos_count=models.Count('gasto')
        )
        return context

# Vistas de ItemPresupuesto
class GastoCreateView(LoginRequiredMixin, CreateView):
    model = Gasto
    form_class = GastoForm
    template_name = 'presupuestos/gasto_form.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.kwargs['presupuesto_pk']})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial = {'presupuesto_pk': self.kwargs['presupuesto_pk']}
        if 'monto' in self.request.GET:
            initial['monto'] = self.request.GET.get('monto')
        if 'nombre' in self.request.GET:
            initial['nombre'] = self.request.GET.get('nombre')
        if 'es_extraccion' in self.request.GET:
            initial['es_extraccion_tarjeta'] = True
        if 'es_aporte' in self.request.GET:
            initial['es_aporte_capital'] = True
            initial['es_extraccion_tarjeta'] = False
            initial['tipo_ingreso'] = 'efectivo'
            if not initial.get('nombre'):
                initial['nombre'] = 'Aporte propio en efectivo'
        if 'tasa' in self.request.GET:
            initial['tasa_interes'] = self.request.GET.get('tasa')
        if 'prox_mes' in self.request.GET:
            initial['monto_proximo_mes'] = self.request.GET.get('prox_mes')

        presupuesto = Presupuesto.objects.filter(pk=self.kwargs['presupuesto_pk']).first()
        if presupuesto and presupuesto.tipo == 'prestamo':
            if 'es_aporte' not in self.request.GET and not initial.get('es_aporte_capital'):
                initial.setdefault('es_extraccion_tarjeta', True)
                initial.setdefault('tasa_interes', presupuesto.tasa_interes_prestamo)
        kwargs['initial'] = initial
        kwargs['user'] = self.request.user
        kwargs['presupuesto'] = presupuesto
        return kwargs

    def form_valid(self, form):
        try:
            presupuesto = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
            form.instance.presupuesto = presupuesto
            
            # Si no se especifica una moneda en el gasto, usar la del presupuesto
            if not form.cleaned_data.get('moneda'):
                form.instance.moneda = presupuesto.moneda
            
            # Guardar el gasto
            gasto = form.save(user=self.request.user)
            
            # Actualizar el monto restante del presupuesto
            presupuesto.actualizar_monto_restante()
            
            messages.success(self.request, 'Gasto creado exitosamente')
            return super().form_valid(form)
        except ValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as e:
            form.add_error(None, f'Error inesperado: {str(e)}')
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
        context['personas_list'] = get_user_recent_personas(self.request.user)
        context['cuentas_list'] = get_user_recent_cuentas(self.request.user)
        return context

class GastoUpdateView(GastoEditableMixin, UpdateView):
    model = Gasto
    form_class = GastoForm
    template_name = 'presupuestos/gasto_form.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.object.presupuesto.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if hasattr(self.object, 'presupuesto'):
            kwargs['presupuesto'] = self.object.presupuesto
        return kwargs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['puede_editar'] = self.object.presupuesto.puede_editar(self.request.user)
        context['personas_list'] = get_user_recent_personas(self.request.user)
        context['cuentas_list'] = get_user_recent_cuentas(self.request.user)
        return context

    def form_valid(self, form):
        response = super().form_valid(form)
        gasto = self.object
        gasto.es_rapido = False
        if gasto.nombre:
            if gasto.nombre.startswith('⚡ '):
                gasto.nombre = gasto.nombre[2:].strip()
            elif gasto.nombre.startswith('⚡'):
                gasto.nombre = gasto.nombre[1:].strip()
        gasto.save()
        messages.success(self.request, 'Gasto actualizado exitosamente')
        return response

class GastoDeleteView(GastoEditableMixin, DeleteView):
    model = Gasto
    template_name = 'presupuestos/gasto_confirm_delete.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.object.presupuesto.pk})

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Gasto eliminado exitosamente')
        return super().delete(request, *args, **kwargs)

class GastoDetailView(GastoUsuarioMixin, DetailView):
    model = Gasto
    template_name = 'presupuestos/gasto_detail.html'
    context_object_name = 'gasto'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['puede_editar'] = self.object.presupuesto.puede_editar(self.request.user)
        return context

class IngresoDetailView(IngresoUsuarioMixin, DetailView):
    model = Ingreso
    template_name = 'presupuestos/ingreso_detail.html'
    context_object_name = 'ingreso'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['puede_editar'] = self.object.presupuesto.puede_editar(self.request.user)
        return context


class IngresoUpdateView(IngresoEditableMixin, UpdateView):
    model = Ingreso
    form_class = IngresoForm
    template_name = 'presupuestos/ingreso_form.html'
    
    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.object.presupuesto.pk})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['user'] = self.request.user
        if hasattr(self.object, 'presupuesto'):
            kwargs['presupuesto'] = self.object.presupuesto
        return kwargs
    
    def form_valid(self, form):
        response = super().form_valid(form)
        ingreso = self.object
        ingreso.es_rapido = False
        if ingreso.nombre:
            if ingreso.nombre.startswith('⚡ '):
                ingreso.nombre = ingreso.nombre[2:].strip()
            elif ingreso.nombre.startswith('⚡'):
                ingreso.nombre = ingreso.nombre[1:].strip()
        ingreso.save()
        self.object.presupuesto.actualizar_monto_restante()
        messages.success(self.request, 'Ingreso actualizado correctamente')
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['editing'] = True
        context['cuentas_list'] = get_user_recent_cuentas(self.request.user)
        if self.object.presupuesto.tipo == 'prestamo':
            context['form_tarjeta'] = TarjetaPrestamoForm()
        return context


class IngresoDeleteView(IngresoEditableMixin, DeleteView):
    model = Ingreso
    template_name = 'presupuestos/ingreso_confirm_delete.html'
    
    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', 
                          kwargs={'pk': self.object.presupuesto.pk})
    
    def delete(self, request, *args, **kwargs):
        self.object = self.get_object()
        presupuesto = self.object.presupuesto
        
        # Guardar el monto antes de eliminar
        monto_ingreso = self.object.monto
        
        # Eliminar el ingreso
        response = super().delete(request, *args, **kwargs)
        
        # Actualizar el monto restante del presupuesto usando el método del modelo
        presupuesto.actualizar_monto_restante()
        
        messages.success(self.request, 'Ingreso eliminado correctamente')
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['puede_editar'] = self.object.presupuesto.puede_editar(self.request.user)
        return context


class IngresoCreateView(LoginRequiredMixin, CreateView):
    model = Ingreso
    form_class = IngresoForm
    template_name = 'presupuestos/ingreso_form.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.kwargs['presupuesto_pk']})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        initial = {'presupuesto_pk': self.kwargs['presupuesto_pk']}
        if 'monto' in self.request.GET:
            initial['monto'] = self.request.GET.get('monto')
        if 'nombre' in self.request.GET:
            initial['nombre'] = self.request.GET.get('nombre')
        if 'es_extraccion' in self.request.GET:
            initial['es_extraccion_tarjeta'] = True
        if 'es_aporte' in self.request.GET:
            initial['es_aporte_capital'] = True
            initial['es_extraccion_tarjeta'] = False
            initial['tipo_ingreso'] = 'efectivo'
            if not initial.get('nombre'):
                initial['nombre'] = 'Aporte propio en efectivo'
        if 'tasa' in self.request.GET:
            initial['tasa_interes'] = self.request.GET.get('tasa')
        if 'prox_mes' in self.request.GET:
            initial['monto_proximo_mes'] = self.request.GET.get('prox_mes')

        presupuesto = Presupuesto.objects.filter(pk=self.kwargs['presupuesto_pk']).first()
        if presupuesto and presupuesto.tipo == 'prestamo':
            if 'es_aporte' not in self.request.GET and not initial.get('es_aporte_capital'):
                initial.setdefault('es_extraccion_tarjeta', True)
                initial.setdefault('tasa_interes', presupuesto.tasa_interes_prestamo)
        kwargs['initial'] = initial
        kwargs['user'] = self.request.user
        kwargs['presupuesto'] = presupuesto
        return kwargs

    def form_valid(self, form):
        try:
            presupuesto = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
            form.instance.presupuesto = presupuesto
            
            # Guardar el ingreso
            ingreso = form.save(user=self.request.user)
            
            # Actualizar el monto restante usando el método del modelo
            presupuesto.actualizar_monto_restante()
            
            messages.success(self.request, 'Ingreso registrado exitosamente')
            return super().form_valid(form)
        except ValidationError as e:
            form.add_error(None, str(e))
            return self.form_invalid(form)
        except Exception as e:
            form.add_error(None, f'Error inesperado: {str(e)}')
            return self.form_invalid(form)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        presupuesto = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
        context['presupuesto'] = presupuesto
        context['cuentas_list'] = get_user_recent_cuentas(self.request.user)
        if presupuesto.tipo == 'prestamo':
            context['form_tarjeta'] = TarjetaPrestamoForm()
        return context


class GastoListView(LoginRequiredMixin, ListView):
    model = Gasto
    template_name = 'presupuestos/gastos.html'
    context_object_name = 'gastos'
    ordering = ['-fecha']

    def get_queryset(self):
        return Gasto.objects.filter(presupuesto_id=self.kwargs['presupuesto_pk'], presupuesto__in=presupuestos_visibles(self.request.user))

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = get_object_or_404(presupuestos_visibles(self.request.user), pk=self.kwargs['presupuesto_pk'])
        return context


@login_required
def compartir_presupuesto(request, pk):
    presupuesto = get_object_or_404(Presupuesto, pk=pk, usuario=request.user)
    if request.method != 'POST':
        return redirect('presupuestos:ver_presupuesto', pk=pk)

    form = CompartirPresupuestoForm(request.POST, presupuesto=presupuesto)
    if form.is_valid():
        compartido = form.save()
        messages.success(request, f'Presupuesto compartido con {compartido.usuario.username}.')
    else:
        messages.error(request, form.errors.as_text())
    return redirect('presupuestos:ver_presupuesto', pk=pk)


@login_required
def quitar_usuario_compartido(request, pk, compartido_id):
    presupuesto = get_object_or_404(Presupuesto, pk=pk, usuario=request.user)
    get_object_or_404(PresupuestoCompartido, pk=compartido_id, presupuesto=presupuesto).delete()
    messages.success(request, 'Usuario quitado del presupuesto compartido.')
    return redirect('presupuestos:ver_presupuesto', pk=pk)


@login_required
def chat_presupuesto(request, pk):
    presupuesto = get_object_or_404(presupuestos_visibles(request.user), pk=pk)
    puede_editar = presupuesto.puede_editar(request.user)
    session_key = f'chat_presupuesto_{presupuesto.pk}'
    chat_messages = request.session.get(session_key, [])

    if request.method == 'POST':
        if not puede_editar:
            messages.error(request, 'No tenes permiso para cargar movimientos en este presupuesto.')
            return redirect('presupuestos:chat_presupuesto', pk=pk)

        texto = request.POST.get('mensaje', '').strip()
        respuesta = procesar_mensaje_chat_presupuesto(presupuesto, texto)
        chat_messages.append({'tipo': 'usuario', 'texto': texto})
        chat_messages.append(respuesta)
        request.session[session_key] = chat_messages[-20:]
        request.session.modified = True
        return redirect('presupuestos:chat_presupuesto', pk=pk)

    return render(request, 'presupuestos/chat_presupuesto.html', {
        'presupuesto': presupuesto,
        'puede_editar': puede_editar,
        'chat_messages': chat_messages,
    })


def procesar_mensaje_chat_presupuesto(presupuesto, texto):
    texto_limpio = texto.strip()
    texto_normalizado = texto_limpio.lower()

    if texto_normalizado in ('hola', 'buenas', 'buen dia', 'buenas tardes', 'buenas noches', 'hey'):
        return {
            'tipo': 'sistema',
            'estado': 'ok',
            'texto': 'Hola. Podes decirme algo como "gaste 2500 en comida empanadas" o "ingreso 100000 sueldo".',
        }

    if texto_normalizado in ('ayuda', 'help', '?'):
        return {
            'tipo': 'sistema',
            'estado': 'ok',
            'texto': 'Ejemplos: "gasto 2500 comida empanadas", "gaste 12000 en nafta", "ingreso 100000 sueldo".',
        }

    tipo_detectado = detectar_tipo_movimiento(texto_normalizado)
    monto = extraer_monto(texto_limpio)
    if not tipo_detectado:
        return {
            'tipo': 'sistema',
            'estado': 'error',
            'texto': 'No se si queres cargar un gasto o un ingreso. Proba con: gasto 2500 comida empanadas.',
        }

    if monto is None:
        return {
            'tipo': 'sistema',
            'estado': 'error',
            'texto': 'No pude leer el monto. Ejemplo: gaste 2500 en comida empanadas.',
        }

    if monto <= 0:
        return {
            'tipo': 'sistema',
            'estado': 'error',
            'texto': 'El monto tiene que ser mayor a cero.',
        }

    detalle = limpiar_detalle_chat(texto_limpio, tipo_detectado)
    categoria_nombre, descripcion = inferir_categoria_y_descripcion(detalle, tipo_detectado)
    fecha_movimiento = extraer_fecha_chat(texto_normalizado)

    if tipo_detectado == 'gasto':
        categoria = Categoria.objects.filter(nombre__iexact=categoria_nombre).first()
        if not categoria:
            categoria = Categoria.objects.create(nombre=categoria_nombre.capitalize())
        nombre = descripcion.capitalize() if descripcion else categoria.nombre
        Gasto.objects.create(
            presupuesto=presupuesto,
            categoria=categoria,
            nombre=nombre,
            descripcion=descripcion,
            monto=monto,
            fecha=fecha_movimiento,
        )
        presupuesto.actualizar_monto_restante()
        return {
            'tipo': 'sistema',
            'estado': 'ok',
            'texto': f'Listo, agregue el gasto "{nombre}" por {monto:.2f}.',
        }

    nombre = descripcion.capitalize() if descripcion else 'Ingreso'
    Ingreso.objects.create(
        presupuesto=presupuesto,
        nombre=nombre,
        descripcion=descripcion,
        monto=monto,
        fecha=fecha_movimiento,
    )
    presupuesto.actualizar_monto_restante()
    return {
        'tipo': 'sistema',
        'estado': 'ok',
        'texto': f'Listo, agregue el ingreso "{nombre}" por {monto:.2f}.',
    }


def detectar_tipo_movimiento(texto):
    if re.search(r'\b(ingreso|ingrese|ingresare|cobre|cobro|cobrare|sueldo|deposito|entrada)\b', texto):
        return 'ingreso'
    if re.search(r'\b(gasto|gaste|gastare|gastos|egreso|pague|pago|pagare|compre|compra|comprare|salida)\b', texto):
        return 'gasto'
    return None


def extraer_monto(texto):
    match = re.search(r'(?<!\w)(?:\$|\+|-)?\s*(\d+(?:[.,]\d{1,2})?)', texto)
    if not match:
        return None
    try:
        return Decimal(match.group(1).replace('.', '').replace(',', '.'))
    except (InvalidOperation, ValueError):
        return None


def limpiar_detalle_chat(texto, tipo):
    detalle = re.sub(r'(?<!\w)(?:\$|\+|-)?\s*\d+(?:[.,]\d{1,2})?', ' ', texto, count=1, flags=re.IGNORECASE)
    palabras = [
        'gasto', 'gaste', 'gastare', 'gastos', 'egreso', 'pague', 'pago', 'pagare', 'compre', 'compra', 'comprare',
        'ingreso', 'ingrese', 'ingresare', 'cobre', 'cobro', 'cobrare', 'deposito', 'entrada',
        'hoy', 'ayer', 'anteayer', 'mañana', 'manana',
        'en', 'de', 'por', 'para', 'del',
    ]
    detalle = re.sub(r'\b(' + '|'.join(palabras) + r')\b', ' ', detalle, flags=re.IGNORECASE)
    return ' '.join(detalle.split())


def inferir_categoria_y_descripcion(detalle, tipo):
    if tipo == 'ingreso':
        return 'Ingreso', detalle
    if not detalle:
        return 'Varios', ''
    partes = detalle.split()
    categoria_nombre = partes[0]
    descripcion = ' '.join(partes[1:]) or detalle
    return categoria_nombre, descripcion


def extraer_fecha_chat(texto):
    ahora = timezone.localtime(timezone.now())
    fecha = ahora.date()

    if re.search(r'\banteayer\b', texto):
        fecha = fecha - timedelta(days=2)
    elif re.search(r'\bayer\b', texto):
        fecha = fecha - timedelta(days=1)
    elif re.search(r'\b(mañana|manana)\b', texto):
        fecha = fecha + timedelta(days=1)

    hora_match = re.search(r'\b(?:a las\s*)?(\d{1,2})(?::|\.)(\d{2})\b', texto)
    if hora_match:
        hora = int(hora_match.group(1))
        minuto = int(hora_match.group(2))
        if 0 <= hora <= 23 and 0 <= minuto <= 59:
            return datetime.combine(fecha, time(hour=hora, minute=minuto))

    return datetime.combine(fecha, ahora.time().replace(microsecond=0))


@login_required
def cerrar_ciclo_prestamo(request, pk):
    presupuesto = get_object_or_404(presupuestos_editables(request.user), pk=pk)
    if request.method == 'POST':
        form = CerrarCicloPrestamoForm(request.POST)
        if form.is_valid():
            ciclo_activo = presupuesto.ciclos_prestamo.filter(esta_cerrado=False).first()
            nuevo_nombre = form.cleaned_data['nuevo_nombre']
            nueva_fecha = form.cleaned_data['nueva_fecha_inicio']
            deuda_sig = form.cleaned_data['deuda_a_devolver']

            if ciclo_activo:
                ciclo_activo.esta_cerrado = True
                ciclo_activo.fecha_fin = nueva_fecha - timedelta(days=1)
                ciclo_activo.fecha_cierre = timezone.now()
                ciclo_activo.save()

            CicloPrestamo.objects.create(
                presupuesto=presupuesto,
                nombre=nuevo_nombre,
                fecha_inicio=nueva_fecha,
                deuda_a_devolver=deuda_sig,
                esta_cerrado=False
            )
            messages.success(request, f"¡Período cerrado con éxito! Se inició '{nuevo_nombre}' con deuda a devolver de ${deuda_sig:,.2f}.")
        else:
            messages.error(request, "Error al cerrar el período. Verifique los datos ingresados.")
    return redirect('presupuestos:ver_presupuesto', pk=pk)


@login_required
def guardar_tarjeta_prestamo(request, pk):
    presupuesto = get_object_or_404(presupuestos_editables(request.user), pk=pk)
    if request.method == 'POST':
        tarjeta_id = request.POST.get('tarjeta_id')
        tarjeta = None
        if tarjeta_id:
            tarjeta = get_object_or_404(presupuesto.tarjetas_prestamo, pk=tarjeta_id)
        form = TarjetaPrestamoForm(request.POST, instance=tarjeta)
        if form.is_valid():
            tarjeta = form.save(commit=False)
            tarjeta.presupuesto = presupuesto
            tarjeta.save()
            messages.success(request, f"Tarjeta '{tarjeta.nombre}' guardada correctamente.")
        else:
            messages.error(request, "Error al guardar la tarjeta. Verifique los campos.")
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('presupuestos:ver_presupuesto', pk=pk)


@login_required
def eliminar_tarjeta_prestamo(request, pk):
    tarjeta = get_object_or_404(TarjetaPrestamo.objects.filter(presupuesto__in=presupuestos_editables(request.user)), pk=pk)
    presupuesto_pk = tarjeta.presupuesto_id
    if request.method == 'POST':
        nombre = tarjeta.nombre
        tarjeta.delete()
        messages.success(request, f"Tarjeta '{nombre}' eliminada.")
    next_url = request.POST.get('next') or request.GET.get('next')
    if next_url:
        return redirect(next_url)
    return redirect('presupuestos:ver_presupuesto', pk=presupuesto_pk)


@login_required
def agregar_diferencia_tarjeta(request, pk):
    presupuesto = get_object_or_404(presupuestos_editables(request.user), pk=pk)
    if request.method == 'POST':
        ciclo_id = request.POST.get('ciclo_id')
        ciclo = None
        if ciclo_id:
            ciclo = presupuesto.ciclos_prestamo.filter(pk=ciclo_id).first()
        if not ciclo:
            ciclo = presupuesto.ciclos_prestamo.filter(esta_cerrado=False).first()

        if not ciclo:
            messages.error(request, "No hay un período activo para agregar la diferencia.")
            return redirect('presupuestos:ver_presupuesto', pk=pk)

        form = DiferenciaTarjetaForm(request.POST, presupuesto=presupuesto)
        if form.is_valid():
            diferencia = form.save(commit=False)
            diferencia.ciclo_prestamo = ciclo
            diferencia.save()
            messages.success(request, f"Diferencia de +${diferencia.monto:,.2f} agregada a '{diferencia.tarjeta.nombre}'.")
        else:
            messages.error(request, "Error al registrar la diferencia. Verifique los datos.")
    return redirect('presupuestos:ver_presupuesto', pk=pk)


@login_required
def eliminar_diferencia_tarjeta(request, pk):
    diferencia = get_object_or_404(
        DiferenciaTarjeta.objects.filter(ciclo_prestamo__presupuesto__in=presupuestos_editables(request.user)),
        pk=pk
    )
    presupuesto_pk = diferencia.ciclo_prestamo.presupuesto_id
    if request.method == 'POST':
        monto = diferencia.monto
        tarjeta_nom = diferencia.tarjeta.nombre
        diferencia.delete()
        messages.success(request, f"Diferencia de ${monto:,.2f} de '{tarjeta_nom}' eliminada.")
    return redirect('presupuestos:ver_presupuesto', pk=presupuesto_pk)
