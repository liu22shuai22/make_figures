"""Public HTTPS transport with DNS pinning and redirects disabled."""
import http.client
import ipaddress
import json
import socket
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlencode

from request_scope import current_scope


def validate_endpoint(url):
    try:
        parts = urlsplit(url)
        if (parts.scheme != "https" or not parts.hostname or parts.username is not None
                or parts.password is not None or parts.fragment or parts.port not in (None, 443)):
            raise ValueError
        host = parts.hostname.encode("idna").decode("ascii")
        scope = current_scope.get()
        if scope is not None and host in scope.endpoints:
            return host, scope.endpoints[host]
        try:
            literal = ipaddress.ip_address(host)
        except ValueError:
            literal = None
        if literal is not None:
            ips = [str(literal)]
        else:
            resolved = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
            ips = list(dict.fromkeys(item[4][0] for item in resolved))
            # TUN proxies may return synthetic benchmark-network addresses.
            # Resolve the actual public destination instead of connecting to those addresses.
            synthetic = ipaddress.ip_network("198.18.0.0/15")
            if ips and all(ipaddress.ip_address(ip) in synthetic for ip in ips):
                ips = public_dns(host)
        addresses = [ipaddress.ip_address(ip) for ip in ips]
        if not addresses or any(not address.is_global or address.is_multicast or address.is_reserved
                                for address in addresses):
            raise ValueError
        if scope is not None:
            scope.endpoints[host] = ips
        return host, ips
    except (ValueError, UnicodeError, OSError):
        raise ValueError("模型接口须为可解析的公网 HTTPS 地址（443 端口）") from None


def public_dns(host):
    query = urlencode({"name": host, "type": "A"})
    request = urllib.request.Request("https://1.1.1.1/dns-query?" + query,
                                     headers={"Accept": "application/dns-json"})
    with model_urlopen(request, timeout=5) as response:
        data = response.read(65_537)
    if len(data) > 65_536:
        raise ValueError("DNS response too large")
    result = json.loads(data)
    if not isinstance(result, dict) or result.get("Status") != 0:
        raise ValueError("DNS lookup failed")
    return list(dict.fromkeys(row["data"] for row in result.get("Answer", [])
                              if isinstance(row, dict) and row.get("type") == 1 and isinstance(row.get("data"), str)))


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, "模型接口重定向已拒绝", {}, None)


class PublicHTTPS(urllib.request.HTTPSHandler):
    def https_open(self, req):
        host, ips = validate_endpoint(req.full_url)

        def connection(address, **kwargs):
            client = http.client.HTTPSConnection(address, context=ssl.create_default_context(), **kwargs)
            if client.host.encode("idna").decode("ascii") != host:
                raise ValueError("模型接口主机不匹配")

            def connect(destination, timeout=socket._GLOBAL_DEFAULT_TIMEOUT, source_address=None, **options):
                last_error = None
                for ip in ips:
                    try:
                        return socket.create_connection((ip, 443), timeout, source_address)
                    except OSError as error:
                        last_error = error
                raise last_error
            client._create_connection = connect
            return client
        return self.do_open(connection, req)


def model_urlopen(request, timeout):
    if current_scope.get() is None:
        return urllib.request.urlopen(request, timeout=timeout)
    validate_endpoint(request.full_url)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect(), PublicHTTPS())
    return opener.open(request, timeout=timeout)
