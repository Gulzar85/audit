import logging

from django.shortcuts import render

logger = logging.getLogger(__name__)


def server_error(request):
    logger.exception('Unhandled server error')
    return render(request, '500.html', status=500)
