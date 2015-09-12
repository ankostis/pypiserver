import sys
import os
from subprocess import call

from pypiserver import core

try:
    from xmlrpc.client import Server, Transport
    from urllib.request import getproxies
    from urllib.parse import urlparse
    from http.client import HTTPConnection
except ImportError:
    from xmlrpclib import Server, Transport  # @UnresolvedImport
    from urllib import getproxies # @UnresolvedImport
    from urlparse import urlparse # @UnresolvedImport
    from httplib import HTTPConnection  # @UnusedImport

def _extract_netloc(url):
    return urlparse(url).netloc

class ProxiedTransport(Transport):
    # From https://www.reddit.com/r/learnpython/comments/1l38mf/i_cant_get_xmlrpc_on_python_3_to_use_an_http_proxy/

    def __init__(self, proxy_netloc, **kwds):
        Transport.__init__(self, **kwds)
        self.proxy_netloc = proxy_netloc

    def make_connection(self, host):
        self.realhost = host
        return HTTPConnection(self.proxy_netloc)

    def send_request(self, host, connection, handler, request_body, debug=False):
        connection.putrequest("POST", 'http://%s%s' % (self.realhost, handler))

def make_pypi_client(url):
    http_proxy_url = getproxies().get("http", None)
    return Server(url,
                  transport=http_proxy_url and
                  ProxiedTransport(_extract_netloc(http_proxy_url)))


def is_stable_version(pversion):
    for x in ("*c", "*@", "*b"):
        if x in pversion:
            return False
    for x in pversion:
        if x.startswith("*final"):
            return True
        if x.startswith("*"):
            return False
    return False


def filter_stable_releases(releases):
    for pkg in releases:
        if is_stable_version(pkg.parsed_version):
            yield pkg


def filter_latest_pkgs(pkgs):
    pkgname2latest = {}

    for x in pkgs:
        pkgname = core.normalize_pkgname(x.pkgname)

        if pkgname not in pkgname2latest:
            pkgname2latest[pkgname] = x
        elif x.parsed_version > pkgname2latest[pkgname].parsed_version:
            pkgname2latest[pkgname] = x

    return pkgname2latest.values()


def build_releases(pkg, versions):
    for x in versions:
        parsed_version = core.parse_version(x)
        if parsed_version > pkg.parsed_version:
            yield core.PkgFile(version=x,
                               parsed_version=parsed_version,
                               pkgname=pkg.pkgname,
                               replaces=pkg)


def find_updates(pkgset, stable_only=True):
    no_releases = set()
    filter_releases = filter_stable_releases if stable_only else (lambda x: x)

    def write(s):
        sys.stdout.write(s)
        sys.stdout.flush()

    latest_pkgs = frozenset(filter_latest_pkgs(pkgset))

    sys.stdout.write(
        "checking %s packages for newer version\n" % len(latest_pkgs),)
    need_update = set()

    pypi = make_pypi_client("https://pypi.python.org/pypi/")

    for count, pkg in enumerate(latest_pkgs):
        if count % 40 == 0:
            write("\n")

        pypi_versions = pypi.package_releases(pkg.pkgname)
        if pypi_versions:
            releases = filter_releases(build_releases(pkg, pypi_versions))
            status = "."
            try:
                need_update.add(max(releases, key=lambda x: x.parsed_version))
                status = "u"
            except ValueError:
                pass
        else:
            status = "e"
            no_releases.add(pkg.pkgname)

        write(status)

    write("\n\n")

    if no_releases:
        sys.stdout.write("no releases found on pypi for %s\n\n" %
                         (", ".join(sorted(no_releases)),))

    return need_update


def update(pkgset, destdir=None, dry_run=False, stable_only=True):
    need_update = find_updates(pkgset, stable_only=stable_only)
    for pkg in sorted(need_update, key=lambda x: x.pkgname):
        sys.stdout.write("# update %s from %s to %s\n" %
                         (pkg.pkgname, pkg.replaces.version, pkg.version))

        cmd = ["pip", "-q", "install", "--no-deps", "-i", "https://pypi.python.org/simple",
               "-d", destdir or os.path.dirname(pkg.replaces.fn),
               "%s==%s" % (pkg.pkgname, pkg.version)]

        sys.stdout.write("%s\n\n" % (" ".join(cmd),))
        if not dry_run:
            call(cmd)
