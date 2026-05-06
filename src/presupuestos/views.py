from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.db import models
from django.core.exceptions import ValidationError
from django.utils import timezone
from itertools import groupby
from core.auth import asignar_presupuestos_sin_usuario
from .models import Presupuesto, Categoria, Gasto, Ingreso
from .forms import PresupuestoForm, CategoriaForm, GastoForm, IngresoForm

class PresupuestoUsuarioMixin(LoginRequiredMixin):
    def get_queryset(self):
        asignar_presupuestos_sin_usuario()
        return Presupuesto.objects.filter(usuario=self.request.user)


class GastoUsuarioMixin(LoginRequiredMixin):
    def get_queryset(self):
        asignar_presupuestos_sin_usuario()
        return Gasto.objects.filter(presupuesto__usuario=self.request.user)


class IngresoUsuarioMixin(LoginRequiredMixin):
    def get_queryset(self):
        asignar_presupuestos_sin_usuario()
        return Ingreso.objects.filter(presupuesto__usuario=self.request.user)


# Vistas de Presupuesto
@login_required
def presupuestos_list(request):
    asignar_presupuestos_sin_usuario()
    presupuestos = Presupuesto.objects.filter(usuario=request.user).order_by('-fecha_creacion')
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
        gastos = list(self.object.gastos.all().order_by('-fecha'))
        ingresos = list(self.object.ingresos.all().order_by('-fecha'))
        
        # Calcular totales
        total_gastos = sum(gasto.monto for gasto in gastos)
        total_ingresos = sum(ingreso.monto for ingreso in ingresos)

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
        context['monto_total_con_ingresos'] = self.object.monto_total + total_ingresos
        
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
            asignar_presupuestos_sin_usuario()
            presupuesto = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'], usuario=self.request.user)
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
        asignar_presupuestos_sin_usuario()
        context['presupuesto'] = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'], usuario=self.request.user)
        return context

class GastoUpdateView(GastoUsuarioMixin, UpdateView):
    model = Gasto
    form_class = GastoForm
    template_name = 'presupuestos/gasto_form.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.object.presupuesto.pk})

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        return context

    def form_valid(self, form):
        # Guardar el gasto con el archivo adjunto
        gasto = form.save()
        messages.success(self.request, 'Gasto actualizado exitosamente')
        return super().form_valid(form)

class GastoDeleteView(GastoUsuarioMixin, DeleteView):
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
        return context

class IngresoDetailView(IngresoUsuarioMixin, DetailView):
    model = Ingreso
    template_name = 'presupuestos/ingreso_detail.html'
    context_object_name = 'ingreso'
    
    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        return context


class IngresoUpdateView(IngresoUsuarioMixin, UpdateView):
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


class IngresoDeleteView(IngresoUsuarioMixin, DeleteView):
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
            asignar_presupuestos_sin_usuario()
            presupuesto = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'], usuario=self.request.user)
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
        asignar_presupuestos_sin_usuario()
        context['presupuesto'] = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'], usuario=self.request.user)
        return context


class GastoListView(LoginRequiredMixin, ListView):
    model = Gasto
    template_name = 'presupuestos/gastos.html'
    context_object_name = 'gastos'
    ordering = ['-fecha']

    def get_queryset(self):
        asignar_presupuestos_sin_usuario()
        return Gasto.objects.filter(presupuesto_id=self.kwargs['presupuesto_pk'], presupuesto__usuario=self.request.user)

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'], usuario=self.request.user)
        return context
