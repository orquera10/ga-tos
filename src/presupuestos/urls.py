from django.urls import path
from . import views
from django.views.generic import RedirectView

app_name = 'presupuestos'

urlpatterns = [
    # App móvil rediseñada (Figma Make)
    path('app/', views.mobile_app_view, name='mobile_app'),

    # URLs de Presupuesto
    path('presupuestos/', views.presupuestos_list, name='index'),
    path('presupuesto/nuevo/', views.PresupuestoCreateView.as_view(), name='crear_presupuesto'),
    path('presupuesto/<int:pk>/editar/', views.PresupuestoUpdateView.as_view(), name='editar_presupuesto'),
    path('presupuesto/<int:pk>/eliminar/', views.PresupuestoDeleteView.as_view(), name='eliminar_presupuesto'),
    path('presupuesto/<int:pk>/compartir/', views.compartir_presupuesto, name='compartir_presupuesto'),
    path('presupuesto/<int:pk>/compartir/<int:compartido_id>/quitar/', views.quitar_usuario_compartido, name='quitar_usuario_compartido'),
    path('presupuesto/<int:pk>/chat/', views.chat_presupuesto, name='chat_presupuesto'),
    path('presupuesto/<int:pk>/cerrar-ciclo/', views.cerrar_ciclo_prestamo, name='cerrar_ciclo_prestamo'),
    path('presupuesto/<int:pk>/guardar-tarjeta/', views.guardar_tarjeta_prestamo, name='guardar_tarjeta_prestamo'),
    path('tarjeta-prestamo/<int:pk>/eliminar/', views.eliminar_tarjeta_prestamo, name='eliminar_tarjeta_prestamo'),
    path('presupuesto/<int:pk>/agregar-diferencia/', views.agregar_diferencia_tarjeta, name='agregar_diferencia_tarjeta'),
    path('diferencia-tarjeta/<int:pk>/eliminar/', views.eliminar_diferencia_tarjeta, name='eliminar_diferencia_tarjeta'),
    path('presupuesto/<int:pk>/transferencia/guardar/', views.guardar_transferencia_fondos, name='guardar_transferencia_fondos'),
    path('transferencia/<int:pk>/editar/', views.TransferenciaFondosUpdateView.as_view(), name='editar_transferencia_fondos'),
    path('transferencia/<int:pk>/eliminar/', views.TransferenciaFondosDeleteView.as_view(), name='eliminar_transferencia_fondos'),
    path('presupuesto/<int:pk>/', views.PresupuestoDetailView.as_view(), name='ver_presupuesto'),

    # URLs de Categoría
    path('categorias/', views.CategoriaListView.as_view(), name='listar_categorias'),
    path('categoria/nueva/', views.CategoriaCreateView.as_view(), name='crear_categoria'),
    path('categoria/<int:pk>/editar/', views.CategoriaUpdateView.as_view(), name='editar_categoria'),
    path('categoria/<int:pk>/eliminar/', views.CategoriaDeleteView.as_view(), name='eliminar_categoria'),

    # URLs de Gasto
    path('presupuesto/<int:presupuesto_pk>/gastos/', views.GastoListView.as_view(), name='listar_gastos'),
    path('presupuesto/<int:presupuesto_pk>/gasto/nuevo/', views.GastoCreateView.as_view(), name='crear_gasto'),
    path('gasto/<int:pk>/', views.GastoDetailView.as_view(), name='ver_gasto'),
    path('gasto/<int:pk>/editar/', views.GastoUpdateView.as_view(), name='editar_gasto'),
    path('gasto/<int:pk>/eliminar/', views.GastoDeleteView.as_view(), name='eliminar_gasto'),
    
    # URLs de Ingreso
    path('presupuesto/<int:presupuesto_pk>/ingreso/nuevo/', views.IngresoCreateView.as_view(), name='crear_ingreso'),
    path('ingreso/<int:pk>/', views.IngresoDetailView.as_view(), name='ver_ingreso'),
    path('ingreso/<int:pk>/editar/', views.IngresoUpdateView.as_view(), name='editar_ingreso'),
    path('ingreso/<int:pk>/eliminar/', views.IngresoDeleteView.as_view(), name='eliminar_ingreso'),

    # Redirección de la raíz a la lista de presupuestos
    path('', RedirectView.as_view(pattern_name='presupuestos:index', permanent=True)),
]
