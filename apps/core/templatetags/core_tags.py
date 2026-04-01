"""Custom template tags and filters."""
from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Access a dict by key in templates: {{ my_dict|get_item:key }}"""
    if isinstance(dictionary, dict):
        return dictionary.get(key, "")
    return ""


@register.filter
def replace(value, args):
    """Replace substring in template: {{ value|replace:'_: ' }}"""
    if not args or ":" not in args:
        return value
    old, new = args.split(":", 1)
    return str(value).replace(old, new)


@register.simple_tag
def url_replace(request, field, value):
    """Replace a single GET parameter while preserving others."""
    dict_ = request.GET.copy()
    dict_[field] = value
    return dict_.urlencode()
