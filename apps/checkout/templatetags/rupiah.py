from django import template

register = template.Library()


@register.filter
def rupiah(value):
    try:
        return f"{int(value):,}".replace(",", ".")
    except (TypeError, ValueError):
        return value