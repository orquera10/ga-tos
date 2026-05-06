from django.urls import include, path
from . import views


urlpatterns = [
    path('login/', views.LoginUsuarioView.as_view(), name='login'),
    path('register/', views.RegistroUsuarioView.as_view(), name='register'),
    path('verification-sent/', views.verification_sent, name='verification_sent'),
    path('resend-verification/', views.resend_verification, name='resend_verification'),
    path('verify/<uuid:token>/', views.verify_email, name='verify_email'),
    path('', include('django.contrib.auth.urls')),
]
