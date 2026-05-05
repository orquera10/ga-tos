import os


def app_version(request):
    version = os.environ.get('SOURCE_COMMIT', 'dev')
    return {'app_version': version[:12]}
