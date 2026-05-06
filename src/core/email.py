from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.template.loader import render_to_string
from django.urls import reverse

from .models import EmailVerificationToken


def enviar_email_verificacion(request, user):
    verification, _ = EmailVerificationToken.objects.get_or_create(user=user)
    verification_url = request.build_absolute_uri(
        reverse('verify_email', kwargs={'token': verification.token})
    )
    context = {
        'user': user,
        'verification_url': verification_url,
    }
    subject = 'Verifica tu cuenta en Ga$tos'
    text_body = render_to_string('registration/emails/verify_email.txt', context)
    html_body = render_to_string('registration/emails/verify_email.html', context)
    email = EmailMultiAlternatives(
        subject=subject,
        body=text_body,
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[user.email],
        reply_to=[settings.EMAIL_HOST_USER] if settings.EMAIL_HOST_USER else None,
    )
    email.attach_alternative(html_body, 'text/html')
    return email.send(fail_silently=False)
