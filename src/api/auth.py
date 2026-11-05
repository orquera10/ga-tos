from functools import wraps
from django.http import JsonResponse
from django.utils import timezone
from .models import ApiToken


def get_user_from_request(request):
    """
    Identifica al usuario a partir de:
    1. Header Authorization: Bearer <token> o Token <token>
    2. Header X-API-Key: <token>
    3. Sesión activa en Django (request.user autenticado)
    """
    token_str = None
    auth_header = request.headers.get('Authorization', '')
    if auth_header:
        parts = auth_header.split()
        if len(parts) == 2 and parts[0].lower() in ('bearer', 'token'):
            token_str = parts[1].strip()

    if not token_str:
        raw_key = request.headers.get('X-API-Key')
        if raw_key:
            token_str = raw_key.strip()

    if token_str:
        try:
            api_token = ApiToken.objects.select_related('user').get(token=token_str)
            if not api_token.user.is_active:
                return None
            # Registrar fecha del último uso de manera diferida
            ApiToken.objects.filter(pk=api_token.pk).update(ultimo_uso=timezone.now())
            return api_token.user
        except ApiToken.DoesNotExist:
            return None

    if getattr(request, 'user', None) and request.user.is_authenticated:
        return request.user

    return None


def api_auth_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        user = get_user_from_request(request)
        if not user:
            return JsonResponse({
                'success': False,
                'error': 'No autorizado. Proporciona un token válido en Authorization: Bearer <token>'
            }, status=401)
        request.api_user = user
        return view_func(request, *args, **kwargs)
    return _wrapped_view
