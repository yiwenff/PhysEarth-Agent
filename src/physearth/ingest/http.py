"""The only place in PhysEarth that opens an outbound connection.

Three rules, all enforced here rather than trusted to callers:

  - the host must be on the allow list, and the URL is always built by us from a DOI or
    an identifier an allowed host itself returned; the agent never supplies a URL
  - a response is read to a byte ceiling, so a slow or enormous document cannot exhaust
    a 2 vCPU instance shared by every visitor
  - a failure comes back as a labelled outcome, never as a silent empty result, because
    "the upstream service is down" and "there is no such paper" must never look alike

`PHYSEARTH_ONLINE=0` closes the whole layer. Nothing else in the system changes when it
is closed: the bundled corpus, the models and the reference data do not go through here.
"""

import json
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request

from physearth import config

ALLOWED_HOSTS = (
    "api.openalex.org",
    "www.ebi.ac.uk",
    "tc.copernicus.org",
    "gmd.copernicus.org",
    "hess.copernicus.org",
    "bg.copernicus.org",
    "acp.copernicus.org",
    "essd.copernicus.org",
    "nhess.copernicus.org",
    "os.copernicus.org",
    "soil.copernicus.org",
    "esurf.copernicus.org",
    "api.github.com",
    "raw.githubusercontent.com",
)

TIMEOUT_S = 20.0
MAX_BYTES = 6_000_000
USER_AGENT = "physearth-agent/0.1 (+https://github.com/zjuiEMLab/PhysEarth-Agent)"

# Operator-only benchmark policy. This blocks the known SMRT v1 reproduction
# repository and the alias observed in earlier traces, without blocking the
# separate SMRT code repository or publisher pages.
_TEST_BLOCKED_REPOSITORIES = {
    ("smrt-model", "smrt_v1_paper"),
    ("smrt-model", "smrt1paper"),
}
_TEST_SOURCE_BLOCKING = False


class Offline(Exception):
    """Raised when the online layer is switched off. Not a fault, a configuration."""


class BlockedSource(Exception):
    """Raised when the operator's testing source policy denies a URL."""


class Upstream(Exception):
    """An allowed host failed to answer. Distinct from answering with nothing."""

    def __init__(self, host, detail):
        super().__init__("%s: %s" % (host, detail))
        self.host = host
        self.detail = detail


def configure_test_source_blocking(enabled):
    """Enable or disable the operator-only testing source block for this process."""
    global _TEST_SOURCE_BLOCKING
    _TEST_SOURCE_BLOCKING = bool(enabled)


def testing_source_blocking():
    """Whether the MCP-side testing source block is active."""
    return bool(_TEST_SOURCE_BLOCKING)


def source_is_blocked(url):
    """Return whether *url* belongs to a blocked SMRT paper repository.

    Matching covers the public repository URL and the API/raw URLs that the GitHub
    integration derives from it. It does not block unrelated GitHub repositories.
    """
    if not _TEST_SOURCE_BLOCKING:
        return False
    parsed = urllib.parse.urlparse(str(url or "").strip())
    host = (parsed.hostname or "").lower()
    parts = [part for part in parsed.path.split("/") if part]
    if host in ("github.com", "raw.githubusercontent.com") and len(parts) >= 2:
        candidate = (parts[0], parts[1].removesuffix(".git"))
    elif host == "api.github.com" and len(parts) >= 3 and parts[0] == "repos":
        candidate = (parts[1], parts[2].removesuffix(".git"))
    else:
        return False
    return candidate in _TEST_BLOCKED_REPOSITORIES


def ensure_source_allowed(url):
    """Reject a testing-blocked source without fetching its contents."""
    if source_is_blocked(url):
        raise BlockedSource("source blocked by the testing source policy")


def online():
    return config.get("PHYSEARTH_ONLINE") != "0"


def _check(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError("only https is allowed, got %r" % parsed.scheme)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("%s is not an allowed host" % parsed.hostname)
    return parsed.hostname


def get_bytes(url, timeout=TIMEOUT_S, max_bytes=MAX_BYTES):
    if not online():
        raise Offline("PHYSEARTH_ONLINE is 0, so nothing is fetched")
    ensure_source_allowed(url)
    host = _check(url)
    started = time.perf_counter()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(
            request, timeout=timeout, context=ssl.create_default_context()
        ) as response:
            payload = response.read(max_bytes + 1)
    except urllib.error.HTTPError as exc:
        raise Upstream(host, "HTTP %s" % exc.code) from exc
    except (urllib.error.URLError, TimeoutError, ssl.SSLError) as exc:
        raise Upstream(host, "%s: %s" % (type(exc).__name__, exc)) from exc
    if len(payload) > max_bytes:
        raise Upstream(host, "the document is larger than the %d byte ceiling" % max_bytes)
    return payload, round(time.perf_counter() - started, 2)


def get_json(url, **kwargs):
    payload, elapsed = get_bytes(url, **kwargs)
    try:
        return json.loads(payload.decode("utf-8")), elapsed
    except (ValueError, UnicodeDecodeError) as exc:
        raise Upstream(_check(url), "the response was not JSON: %s" % exc) from exc


def get_text(url, **kwargs):
    payload, elapsed = get_bytes(url, **kwargs)
    return payload.decode("utf-8", errors="replace"), elapsed
