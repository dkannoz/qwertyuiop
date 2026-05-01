# Adapted for use in MediaFlowProxy from:
# https://github.com/einars/js-beautify/blob/master/python/jsbeautifier/unpackers/packer.py
# Unpacker for Dean Edward's p.a.c.k.e.r, a part of javascript beautifier
# by Einar Lielmanis <einar@beautifier.io>
#
#     written by Stefano Sanfilippo <a.little.coder@gmail.com>
#
# usage:
#
# if detect(some_string):
#     unpacked = unpack(some_string)
#
"""Unpacker for Dean Edward's p.a.c.k.e.r"""

import re
from bs4 import BeautifulSoup, SoupStrainer
from urllib.parse import urljoin, urlparse
import logging


logger = logging.getLogger(__name__)


def detect(source):
    if "eval(function(p,a,c,k,e,d)" in source:
        mystr = "smth"
        return mystr is not None


def unpack(source):
    """Unpacks P.A.C.K.E.R. packed js code."""
    payload, symtab, radix, count = _filterargs(source)

    if count != len(symtab):
        raise UnpackingError("Malformed p.a.c.k.e.r. symtab.")

    try:
        unbase = Unbaser(radix)
    except TypeError:
        raise UnpackingError("Unknown p.a.c.k.e.r. encoding.")

    def lookup(match):
        """Look up symbols in the synthetic symtab."""
        word = match.group(0)
        return symtab[unbase(word)] or word

    payload = payload.replace("\\\\", "\\").replace("\\'", "'")
    source = re.sub(r"\b\w+\b", lookup, payload)
    return _replacestrings(source)


def _filterargs(source):
    """Juice from a source file the four args needed by decoder."""
    juicers = [
        (r"}\('(.*)', *(\d+|\[\]), *(\d+), *'(.*)'\.split\('\|'\), *(\d+), *(.*)\)\)"),
        (r"}\('(.*)', *(\d+|\[\]), *(\d+), *'(.*)'\.split\('\|'\)"),
    ]
    for juicer in juicers:
        args = re.search(juicer, source, re.DOTALL)
        if args:
            a = args.groups()
            if a[1] == "[]":
                a = list(a)
                a[1] = 62
                a = tuple(a)
            try:
                return a[0], a[3].split("|"), int(a[1]), int(a[2])
            except ValueError:
                raise UnpackingError("Corrupted p.a.c.k.e.r. data.")

    # could not find a satisfying regex
    raise UnpackingError("Could not make sense of p.a.c.k.e.r data (unexpected code structure)")


def _replacestrings(source):
    """Strip string lookup table (list) and replace values in source."""
    match = re.search(r'var *(_\w+)\=\["(.*?)"\];', source, re.DOTALL)

    if match:
        varname, strings = match.groups()
        startpoint = len(match.group(0))
        lookup = strings.split('","')
        variable = "%s[%%d]" % varname
        for index, value in enumerate(lookup):
            source = source.replace(variable % index, '"%s"' % value)
        return source[startpoint:]
    return source


class Unbaser(object):
    """Functor for a given base. Will efficiently convert
    strings to natural numbers."""

    ALPHABET = {
        62: "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ",
        95: (" !\"#$%&'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~"),
    }

    def __init__(self, base):
        self.base = base

        # fill elements 37...61, if necessary
        if 36 < base < 62:
            if not hasattr(self.ALPHABET, self.ALPHABET[62][:base]):
                self.ALPHABET[base] = self.ALPHABET[62][:base]
        # attrs = self.ALPHABET
        # print ', '.join("%s: %s" % item for item in attrs.items())
        # If base can be handled by int() builtin, let it do it for us
        if 2 <= base <= 36:
            self.unbase = lambda string: int(string, base)
        else:
            # Build conversion dictionary cache
            try:
                self.dictionary = dict((cipher, index) for index, cipher in enumerate(self.ALPHABET[base]))
            except KeyError:
                raise TypeError("Unsupported base encoding.")

            self.unbase = self._dictunbaser

    def __call__(self, string):
        return self.unbase(string)

    def _dictunbaser(self, string):
        """Decodes a  value to an integer."""
        ret = 0
        for index, cipher in enumerate(string[::-1]):
            ret += (self.base**index) * self.dictionary[cipher]
        return ret


class UnpackingError(Exception):
    """Badly packed source or general error. Argument is a
    meaningful description."""

    pass


def _match_packed(html: str, base_url: str, patterns: list[str]) -> str | None:
    """Find a p.a.c.k.e.d JS block in *html* and return the first matching pattern."""
    soup = BeautifulSoup(html, "lxml", parse_only=SoupStrainer("script"))
    for script in soup.find_all("script"):
        text = script.text or ""
        if not detect(text):
            continue
        unpacked_code = unpack(text)
        for pattern in patterns:
            match = re.search(pattern, unpacked_code)
            if match:
                extracted_url = match.group(1)
                if not urlparse(extracted_url).scheme:
                    extracted_url = urljoin(base_url, extracted_url)
                return extracted_url
    return None


async def eval_solver(self, url: str, headers: dict[str, str] | None, patterns: list[str]) -> str:
    """Resolve a URL by unpacking p.a.c.k.e.d JS, with optional Byparr fallback.

    Order:
    1. Direct request via self._make_request (fast path).
    2. If BYPARR_URL is set: fetch through Byparr and retry the match.
    """
    from mediaflow_proxy.configs import settings

    primary_exc: Exception | None = None

    # 1. Direct request
    try:
        response = await self._make_request(url, headers=headers)
        result = _match_packed(response.text, url, patterns)
        if result:
            return result
        primary_exc = UnpackingError("No p.a.c.k.e.d JS / pattern not matched in direct response")
    except Exception as e:
        primary_exc = e

    # 2. Byparr fallback
    if settings.byparr_url:
        from mediaflow_proxy.utils.byparr import fetch_via_byparr, ByparrError

        try:
            html = await fetch_via_byparr(url)
            result = _match_packed(html, url, patterns)
            if result:
                logger.info("eval_solver: Byparr fallback succeeded for %s", url)
                return result
            logger.warning("eval_solver: Byparr fetched %s but no pattern matched", url)
        except ByparrError as e:
            logger.warning("eval_solver: Byparr fallback failed for %s: %s", url, e)
            primary_exc = e

    logger.error("Eval solver failed for %s: %s", url, primary_exc)
    raise UnpackingError("Error in eval_solver") from primary_exc
