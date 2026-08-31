from django import template

register = template.Library()


@register.filter
def subtract(value, arg):
    if value is None or arg is None:
        return None
    return value - arg
