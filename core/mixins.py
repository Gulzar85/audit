from django.views.decorators.cache import never_cache
from django.utils.decorators import method_decorator


class NeverCacheMixin:
    @method_decorator(never_cache)
    def dispatch(self, *args, **kwargs):
        return super().dispatch(*args, **kwargs)
