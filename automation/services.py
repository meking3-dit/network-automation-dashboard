from contextlib import contextmanager

import paramiko
from netmiko import ConnectHandler


def parse_commands(value):
    return [line.strip() for line in (value or "").splitlines() if line.strip() and not line.lstrip().startswith("#")]


def open_jump_tunnel(device):
    """Log in to the jump server and return (client, channel) forwarded to the device."""
    credential = device.jump_credential
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            device.jump_host,
            port=device.jump_port,
            username=credential.username,
            password=credential.password,
            look_for_keys=False,
            allow_agent=False,
            timeout=30,
        )
        channel = client.get_transport().open_channel("direct-tcpip", (device.host, device.port), ("127.0.0.1", 0))
    except Exception:
        client.close()
        raise
    return client, channel


@contextmanager
def netmiko_connection(device):
    jump_client = None
    params = device.connection_params()
    if device.use_jump_server:
        jump_client, params["sock"] = open_jump_tunnel(device)
    try:
        connection = ConnectHandler(**params)
        try:
            if device.credential.secret:
                connection.enable()
            yield connection
        finally:
            connection.disconnect()
    finally:
        if jump_client:
            jump_client.close()
