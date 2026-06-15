from django import template
from django.utils.translation import gettext as _

register = template.Library()

_MONTH_KEYS = [
    "January", "February", "March", "April",
    "May", "June", "July", "August",
    "September", "October", "November", "December",
]


@register.filter
def month_name(month_num):
    """Convert a month integer (1-12) to a translated month name."""
    try:
        return _(_MONTH_KEYS[int(month_num) - 1])
    except (ValueError, IndexError, TypeError):
        return month_num
