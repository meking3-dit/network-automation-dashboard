from contextlib import contextmanager

from netmiko import ConnectHandler


def parse_commands(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip() and not line.lstrip().startswith("#")]


@contextmanager
def netmiko_connection(device):
    connection = ConnectHandler(**device.connection_params())
    try:
        if device.credential.secret:
            connection.enable()
        yield connection
    finally:
        connection.disconnect()
