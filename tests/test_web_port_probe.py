import os
import socket
import unittest

from main import _web_port_available


@unittest.skipIf(os.name == "nt", "TIME_WAIT reuse semantics are POSIX-specific")
class WebPortProbeTests(unittest.TestCase):
    def test_time_wait_from_previous_instance_does_not_block_restart(self):
        # Simulate the old instance: listen, accept a browser connection,
        # then close server-side first so the port is left in TIME_WAIT.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        listener.listen(1)
        client = socket.create_connection(("127.0.0.1", port))
        conn, _ = listener.accept()
        conn.close()
        listener.close()
        try:
            self.assertTrue(_web_port_available("127.0.0.1", port))
        finally:
            client.close()

    def test_active_listener_is_still_detected(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        try:
            self.assertFalse(_web_port_available("127.0.0.1", listener.getsockname()[1]))
        finally:
            listener.close()


if __name__ == "__main__":
    unittest.main()
