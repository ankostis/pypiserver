#! /usr/bin/env py.test

import pytest
import py
from pypiserver.core import parse_version, PkgFile, guess_pkgname_and_version
from pypiserver.manage import (is_stable_version, build_releases,
                               find_updates, filter_stable_releases,
                               filter_latest_pkgs, _extract_netloc)
import sys
import os
import subprocess as sb
import time
from warnings import warn
import tempfile

try:
    from xmlrpc.client import ProtocolError
except ImportError:
    from xmlrpclib import ProtocolError# @UnresolvedImport


def touch_files(root, files):
    root = py.path.local(root)
    for f in files:
        root.join(f).ensure()


def pkgfile_from_path(fn):
    pkgname, version = guess_pkgname_and_version(fn)
    return PkgFile(root=py.path.local(fn).parts()[1].strpath,
                   fn=fn, pkgname=pkgname, version=version, parsed_version=parse_version(version))


@pytest.mark.parametrize(
    ("version", "is_stable"),
    [("1.0", True),
     ("0.0.0", True),
     ("1.1beta1", False),
     ("1.2.10-123", True),
     ("5.5.0-DEV", False),
     ("1.2-rc1", False),
     ("1.0b1", False)])
def test_is_stable_version(version, is_stable):
    parsed_version = parse_version(version)
    assert is_stable_version(parsed_version) == is_stable


def test_build_releases():
    p = pkgfile_from_path('/home/ralf/pypiserver/d/greenlet-0.2.zip')

    expected = dict(parsed_version=('00000000', '00000003', '*final'),
                    pkgname='greenlet',
                    replaces=p,
                    version='0.3.0')

    res, = list(build_releases(p, ["0.3.0"]))
    assert res.__dict__ == expected


def test_filter_stable_releases():
    p = pkgfile_from_path('/home/ralf/pypiserver/d/greenlet-0.2.zip')
    assert list(filter_stable_releases([p])) == [p]

    p2 = pkgfile_from_path('/home/ralf/pypiserver/d/greenlet-0.5rc1.zip')
    assert list(filter_stable_releases([p2])) == []


def test_filter_latest_pkgs():
    paths = ["/home/ralf/greenlet-0.2.zip",
             "/home/ralf/foo/baz-1.0.zip"
             "/home/ralf/bar/greenlet-0.3.zip"]
    pkgs = [pkgfile_from_path(x) for x in paths]

    assert frozenset(filter_latest_pkgs(pkgs)) == frozenset(pkgs[1:])


def test_filter_latest_pkgs_case_insensitive():
    paths = ["/home/ralf/greenlet-0.2.zip",
             "/home/ralf/foo/baz-1.0.zip"
             "/home/ralf/bar/Greenlet-0.3.zip"]
    pkgs = [pkgfile_from_path(x) for x in paths]

    assert frozenset(filter_latest_pkgs(pkgs)) == frozenset(pkgs[1:])


def find_file_in_PATH(fname):
    for path in os.environ["PATH"].split(os.pathsep):
        path = path.strip('"')
        fpath = os.path.join(path, fname)
        if os.path.isfile(fpath):
            return fpath


@pytest.mark.parametrize(
    ('proxy_url', 'exp_netloc'),
    [
     ("localhost", "localhost"),
     ("localhost:8899", "localhost:8899"),
     ("http://localhost:8899/", "localhost:8899")
    ],
)
def test_extract_netloc(proxy_url, exp_netloc):
    _extract_netloc(proxy_url)


@pytest.mark.skipif(True, reason="SubProcesses lockup; run it from main().")
def test_proxying_updates():
    pkg = PkgFile(pkgname='pypiserver', parsed_version=('1', '1', '6'))
    proxy_script_path = find_file_in_PATH('proxy.py')
    if not proxy_script_path:
        raise ImportError("Run `pip instal proxy.py`!")
    proxy_url = "http://localhost:8899/"
    os.environ['HTTP_PROXY'] = proxy_url
    proxy_script_cmd = 'python %s --port 8899 --log-level DEBUG' % proxy_script_path

    with tempfile.TemporaryFile('r+t') as err_file:
        proc = sb.Popen(proxy_script_cmd.split(),
                        stderr=err_file, universal_newlines=True)
        try:
            time.sleep(1) # Give time to proxy-script to startup.
            try:
                find_updates([pkg])
            except ProtocolError as ex:
                # pypi failed to respond, ... another time!
                print("Bad moment for PyPi: %s" % ex)
                return
        finally:
            proc.kill()
            stderr = err_file.read()
            print('STDERR: %s' % stderr)
            assert '127.0.0.1' in stderr

if __name__ == '__main__':
    test_proxying_updates()
