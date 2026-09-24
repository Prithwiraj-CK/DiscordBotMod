import unittest

from bot import _transport_mode


class TransportModeTests(unittest.TestCase):
    def test_rest_is_default_and_invalid_values_fail_closed_to_rest(self):
        self.assertEqual("rest", _transport_mode(""))
        self.assertEqual("rest", _transport_mode("unexpected"))

    def test_gateway_requires_explicit_opt_in(self):
        self.assertEqual("gateway", _transport_mode("gateway"))
        self.assertEqual("rest", _transport_mode("REST"))


if __name__ == "__main__":
    unittest.main()
