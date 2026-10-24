import os
import socket
import unittest


class IsolationTests(unittest.TestCase):
    def test_read_only_project(self):
        with self.assertRaises(OSError):
            with open('/code/host_write_denied', 'w') as handle:
                handle.write('attempted')

    def test_container_is_not_root(self):
        self.assertNotEqual(os.geteuid(), 0)

    def test_external_network_blocked(self):
        connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(0.5)
        try:
            with self.assertRaises(OSError):
                connection.connect(('1.1.1.1', 443))
        finally:
            connection.close()
