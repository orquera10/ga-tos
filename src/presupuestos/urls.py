from django.urls import path
from . import views
from django.views.generic import RedirectView

app_name = 'presupuestos'

urlpatterns = [
    # URLs de Presupuesto
    path('presupuestos/', views.presupuestos_list, name='index'),
    path('presupuesto/nuevo/', views.PresupuestoCreateView.as_view(), name='crear_presupuesto'),
    path('presupuesto/<int:pk>/editar/', views.PresupuestoUpdateView.as_view(), name='editar_presupuesto'),
    path('presupuesto/<int:pk>/eliminar/', views.PresupuestoDeleteView.as_view(), name='eliminar_presupuesto'),
    path('presupuesto/<int:pk>/', views.PresupuestoDetailView.as_view(), name='ver_presupuesto'),

    # URLs de Categoría
    path('categorias/', views.CategoriaListView.as_view(), name='listar_categorias'),
    path('categoria/nueva/', views.CategoriaCreateView.as_view(), name='crear_categoria'),
    path('categoria/<int:pk>/editar/', views.CategoriaUpdateView.as_view(), name='editar_categoria'),
    path('categoria/<int:pk>/eliminar/', views.CategoriaDeleteView.as_view(), name='eliminar_categoria'),

    # URLs de Gasto
    path('presupuesto/<int:presupuesto_pk>/gasto/nuevo/', views.GastoCreateView.as_view(), name='crear_gasto'),

    # URLs de Gasto
    path('presupuesto/<int:presupuesto_pk>/gastos/', views.GastoListView.as_view(), name='listar_gastos'),
    path('presupuesto/<int:presupuesto_pk>/gasto/nuevo/', views.GastoCreateView.as_view(), name='crear_gasto'),
    path('gasto/<int:pk>/', views.GastoDetailView.as_view(), name='ver_gasto'),
    path('gasto/<int:pk>/editar/', views.GastoUpdateView.as_view(), name='editar_gasto'),
    path('gasto/<int:pk>/eliminar/', views.GastoDeleteView.as_view(), name='eliminar_gasto'),

    # Redirección de la raíz a la lista de presupuestos
    path('', RedirectView.as_view(pattern_name='presupuestos:index', permanent=True)),
]
