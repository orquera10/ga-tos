from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse_lazy
from django.views.generic import CreateView, UpdateView, DeleteView, ListView, DetailView
from django.db import models
from .models import Presupuesto, Categoria, Gasto
from .forms import PresupuestoForm, CategoriaForm, GastoForm

# Vistas de Presupuesto
def presupuestos_list(request):
    presupuestos = Presupuesto.objects.all().order_by('-fecha_creacion')
    return render(request, 'presupuestos/index.html', {'presupuestos': presupuestos})

class PresupuestoDetailView(DetailView):
    model = Presupuesto
    template_name = 'presupuestos/ver_presupuesto.html'
    context_object_name = 'presupuesto'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['gastos'] = self.object.gastos.all().order_by('-fecha')
        return context

class PresupuestoCreateView(CreateView):
    model = Presupuesto
    form_class = PresupuestoForm
    template_name = 'presupuestos/presupuesto_form.html'
    success_url = reverse_lazy('presupuestos:index')

    def form_valid(self, form):
        messages.success(self.request, 'Presupuesto creado exitosamente')
        return super().form_valid(form)

class PresupuestoUpdateView(UpdateView):
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

class PresupuestoDeleteView(DeleteView):
    model = Presupuesto
    template_name = 'presupuestos/presupuesto_confirm_delete.html'
    success_url = reverse_lazy('presupuestos:index')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Presupuesto eliminado exitosamente')
        return super().delete(request, *args, **kwargs)

# Vistas de Categoría
class CategoriaCreateView(CreateView):
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

class CategoriaUpdateView(UpdateView):
    model = Categoria
    form_class = CategoriaForm
    template_name = 'presupuestos/categoria_form.html'
    success_url = reverse_lazy('presupuestos:listar_categorias')

    def form_valid(self, form):
        messages.success(self.request, 'Categoría actualizada exitosamente')
        return super().form_valid(form)

class CategoriaDeleteView(DeleteView):
    model = Categoria
    template_name = 'presupuestos/categoria_confirm_delete.html'
    success_url = reverse_lazy('presupuestos:listar_categorias')

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Categoría eliminada exitosamente')
        return super().delete(request, *args, **kwargs)

class CategoriaListView(ListView):
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
class GastoCreateView(CreateView):
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
            presupuesto = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'])
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
        context['presupuesto'] = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'])
        return context

class GastoUpdateView(UpdateView):
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

class GastoDeleteView(DeleteView):
    model = Gasto
    template_name = 'presupuestos/gasto_confirm_delete.html'

    def get_success_url(self):
        return reverse_lazy('presupuestos:ver_presupuesto', kwargs={'pk': self.object.presupuesto.pk})

    def delete(self, request, *args, **kwargs):
        messages.success(self.request, 'Gasto eliminado exitosamente')
        return super().delete(request, *args, **kwargs)

class GastoDetailView(DetailView):
    model = Gasto
    template_name = 'presupuestos/gasto_detail.html'
    context_object_name = 'gasto'

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = self.object.presupuesto
        return context

class GastoListView(ListView):
    model = Gasto
    template_name = 'presupuestos/gastos.html'
    context_object_name = 'gastos'
    ordering = ['-fecha']

    def get_queryset(self):
        return Gasto.objects.filter(presupuesto_id=self.kwargs['presupuesto_pk'])

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['presupuesto'] = get_object_or_404(Presupuesto, pk=self.kwargs['presupuesto_pk'])
        return context
