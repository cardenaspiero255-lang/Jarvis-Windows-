from pricing import line_total
from coupons import apply_discount


def checkout_total(items, discount_percent=0):
    subtotal = sum(line_total(price, quantity) for price, quantity in items)
    return apply_discount(subtotal, discount_percent)
