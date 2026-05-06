from django.shortcuts import render
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import get_user_model
from django.contrib.auth.views import LoginView
from django.shortcuts import redirect
from django.utils import timezone
from django.views.generic import FormView

from .email import enviar_email_verificacion
from .forms import LoginUsuarioForm, RegistroUsuarioForm
from .models import EmailVerificationToken


class LoginUsuarioView(LoginView):
    template_name = 'registration/login.html'
    authentication_form = LoginUsuarioForm

    def form_invalid(self, form):
        inactive_user = getattr(form, 'inactive_user', None)
        if inactive_user:
            self.request.session['pending_verification_email'] = inactive_user.email
            context = self.get_context_data(form=form)
            context['inactive_user_email'] = inactive_user.email
            return self.render_to_response(context)
        return super().form_invalid(form)


class RegistroUsuarioView(FormView):
    template_name = 'registration/register.html'
    form_class = RegistroUsuarioForm

    def form_valid(self, form):
        user = form.save()
        enviar_email_verificacion(self.request, user)
        self.request.session['pending_verification_email'] = user.email
        return redirect('verification_sent')


def verification_sent(request):
    return render(request, 'registration/verification_sent.html', {
        'email': request.session.get('pending_verification_email'),
    })


def resend_verification(request):
    email = request.session.get('pending_verification_email') or request.POST.get('email')
    if not email:
        messages.error(request, 'No encontramos un email pendiente de verificacion.')
        return redirect('login')

    User = get_user_model()
    user = User.objects.filter(email__iexact=email, is_active=False).first()
    if not user:
        messages.error(request, 'No encontramos una cuenta pendiente para ese email.')
        return redirect('login')

    enviar_email_verificacion(request, user)
    request.session['pending_verification_email'] = user.email
    messages.success(request, 'Te reenviamos el enlace de activacion.')
    return redirect('verification_sent')


def verify_email(request, token):
    verification = EmailVerificationToken.objects.select_related('user').filter(token=token).first()
    if not verification:
        return render(request, 'registration/verification_invalid.html', status=404)

    user = verification.user
    if not user.is_active:
        user.is_active = True
        user.save(update_fields=['is_active'])
    if not verification.is_verified:
        verification.verified_at = timezone.now()
        verification.save(update_fields=['verified_at'])

    login(request, user)
    messages.success(request, 'Tu cuenta fue verificada correctamente.')
    return redirect('presupuestos:index')
