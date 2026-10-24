import unittest
from pricing import line_total
from coupons import apply_discount
from orders import checkout_total


class CheckoutTests(unittest.TestCase):
    def test_price(self):
        self.assertEqual(line_total(8, 3), 24)

    def test_zero_quantity(self):
        self.assertEqual(line_total(20, 0), 0)

    def test_negative_quantity(self):
        self.assertEqual(line_total(7, -2), -14)

    def test_large_quantity(self):
        self.assertEqual(line_total(125, 4), 500)

    def test_discount(self):
        self.assertEqual(apply_discount(100, 20), 80)

    def test_order_one_item(self):
        self.assertEqual(checkout_total([(10, 2)]), 20)

    def test_order_multiple(self):
        self.assertEqual(checkout_total([(10, 2), (5, 3)]), 35)

    def test_order_discount(self):
        self.assertEqual(checkout_total([(10, 2), (10, 1)], 10), 27)
