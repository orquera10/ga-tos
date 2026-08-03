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
from datetime import datetime, time, timedelta
import re
from core.auth import asignar_presupuestos_sin_usuario
from .models import Presupuesto, PresupuestoCompartido, Categoria, Gasto, Ingreso
from .forms import PresupuestoForm, CompartirPresupuestoForm, CategoriaForm, GastoForm, IngresoForm


def presupuestos_visibles(user):
    asignar_presupuestos_sin_usuario()
    return Presupuesto.objects.filter(Q(usuario=user) | Q(compartidos__usuario=user)).distinct()


def presupuestos_editables(user):
    asignar_presupuestos_sin_usuario()
    return Presupuesto.objects.filter(Q(usuario=user) | Q(compartidos__usuario=user, compartidos__permiso='editar')).distinct()

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
        fecha = transaccion.fecha
        if timezone.is_aware(fecha):
            return timezone.localtime(fecha)
        return fecha

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        
        # Obtener gastos e ingresos ordenados
        gastos = list(self.object.gastos.select_related('categoria').order_by('-fecha'))
        ingresos = list(self.object.ingresos.all().order_by('-fecha'))
        
        # Calcular totales
        total_gastos = sum(gasto.monto for gasto in gastos)
        total_ingresos = sum(ingreso.monto for ingreso in ingresos)

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
        
        # Agregar al contexto
        context['gastos'] = gastos
        context['ingresos'] = ingresos
        context['transacciones_por_dia'] = transacciones_por_dia
        context['total_gastos'] = total_gastos
        context['total_ingresos'] = total_ingresos
        context['resumen_gastos_por_tipo'] = resumen_gastos_por_tipo
        context['monto_total_con_ingresos'] = self.object.monto_total + total_ingresos
        context['puede_editar'] = self.object.puede_editar(self.request.user)
        context['es_duenio'] = self.object.usuario_id == self.request.user.id
        context['compartir_form'] = CompartirPresupuestoForm(presupuesto=self.object)
        context['usuarios_compartidos'] = self.object.compartidos.select_related('usuario').order_by('usuario__username')
        
        # Para depuración
        context['debug_gastos_count'] = len(gastos)
        context['debug_ingresos_count'] = len(ingresos)
        
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
        kwargs['initial'] = {'presupuesto_pk': self.kwargs['presupuesto_pk']}
        return kwargs

    def form_valid(self, form):
        try:
            presupuesto = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
            form.instance.presupuesto = presupuesto
            
            # Si no se especifica una moneda en el gasto, usar la del presupuesto
            if not form.cleaned_data.get('moneda'):
                form.instance.moneda = presupuesto.moneda
            
            # Guardar el gasto
            gasto = form.save()
            
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
        return context

class GastoUpdateView(GastoEditableMixin, UpdateView):
    model = Gasto
    form_class = GastoForm
    template_name = 'presupuestos/gasto_form.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.object.presupuesto.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['puede_editar'] = self.object.presupuesto.puede_editar(self.request.user)
        return context

    def form_valid(self, form):
        # Guardar el gasto con el archivo adjunto
        gasto = form.save()
        messages.success(self.request, 'Gasto actualizado exitosamente')
        return super().form_valid(form)

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
        return context


class IngresoUpdateView(IngresoEditableMixin, UpdateView):
    model = Ingreso
    form_class = IngresoForm
    template_name = 'presupuestos/ingreso_form.html'
    
    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_ingreso', kwargs={'pk': self.object.pk})
    
    def form_valid(self, form):
        # Guardar el monto anterior para el cálculo
        old_monto = self.get_object().monto
        
        # Guardar el formulario para obtener el nuevo ingreso
        response = super().form_valid(form)
        
        # Actualizar el monto restante del presupuesto usando el método del modelo
        self.object.presupuesto.actualizar_monto_restante()
        
        messages.success(self.request, 'Ingreso actualizado correctamente')
        return response
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        context['editing'] = True
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
        return context


class IngresoCreateView(LoginRequiredMixin, CreateView):
    model = Ingreso
    form_class = IngresoForm
    template_name = 'presupuestos/ingreso_form.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.kwargs['presupuesto_pk']})

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs['initial'] = {'presupuesto_pk': self.kwargs['presupuesto_pk']}
        return kwargs

    def form_valid(self, form):
        try:
            presupuesto = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
            form.instance.presupuesto = presupuesto
            
            # Guardar el ingreso
            ingreso = form.save()
            
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
        context['presupuesto'] = get_object_or_404(presupuestos_editables(self.request.user), pk=self.kwargs['presupuesto_pk'])
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
