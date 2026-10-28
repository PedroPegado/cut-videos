"""Isolated yt-dlp entry point; rejects private network destinations."""
import ipaddress
import socket
import yt_dlp

original_connect = socket.socket.connect
original_connect_ex = socket.socket.connect_ex


def public_address(address):
    if not isinstance(address, tuple):
        raise OSError('Unsupported network destination')
    for result in socket.getaddrinfo(address[0], address[1], type=socket.SOCK_STREAM):
        ip = ipaddress.ip_address(result[4][0].split('%')[0])
        if not ip.is_global or (ip.version == 6 and ip.ipv4_mapped and not ip.ipv4_mapped.is_global):
            raise OSError('Private network destinations are prohibited')


def connect(self, address):
    public_address(address)
    return original_connect(self, address)


def connect_ex(self, address):
    public_address(address)
    return original_connect_ex(self, address)


if __name__ == '__main__':
    socket.socket.connect = connect
    socket.socket.connect_ex = connect_ex
    yt_dlp.main()
