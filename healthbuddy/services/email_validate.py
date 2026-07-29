"""Email validation used at sign-up: format check + "does this domain
actually exist and accept mail" check.

The old regex accepted anything shaped like x@y.z, so obviously-fake
addresses like "asdf@asdf123.zzz" sailed through registration. This module
adds a real DNS lookup for the domain's MX (mail exchanger) records - the
same check real signup forms use - so we reject domains that can't
possibly receive email, while still accepting any legitimately
registered domain (Gmail, a company's own domain, etc) without needing to
know about it in advance.

We deliberately do NOT try to verify the mailbox itself (e.g. an SMTP
handshake, or a known-provider allowlist) - that's unreliable, often
blocked by mail servers, and would reject real addresses on domains we
don't recognize. Checking the domain can receive mail at all is the
right amount of validation here.
"""
import re
import socket

try:
    import dns.resolver
    _HAVE_DNSPYTHON = True
except ImportError:  # pragma: no cover - falls back if dnspython isn't installed
    _HAVE_DNSPYTHON = False

EMAIL_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9._%+-]*[A-Za-z0-9])?"
    r"@"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?\.)+"
    r"[A-Za-z]{2,}$"
)

# A handful of well-known one-off/disposable email domains people use to
# dodge signup forms. DNS won't catch these (they're real, working mail
# domains) so they need an explicit list.
_DISPOSABLE_DOMAINS = {
    "mailinator.com", "tempmail.com", "temp-mail.org", "guerrillamail.com",
    "10minutemail.com", "yopmail.com", "throwawaymail.com", "trashmail.com",
    "fakeinbox.com", "getnada.com", "sharklasers.com",
}

_DNS_TIMEOUT_SECONDS = 3


def _domain_accepts_mail(domain):
    """Returns True if the domain has MX records (or, failing that, an A/AAAA
    record it could fall back to per RFC 5321). Returns False only when DNS
    positively tells us the domain doesn't exist - any lookup/network
    failure fails OPEN so a flaky resolver never blocks a real signup."""
    if _HAVE_DNSPYTHON:
        try:
            resolver = dns.resolver.Resolver()
            resolver.timeout = _DNS_TIMEOUT_SECONDS
            resolver.lifetime = _DNS_TIMEOUT_SECONDS
            resolver.resolve(domain, "MX")
            return True
        except (dns.resolver.NXDOMAIN, dns.resolver.NoAnswer):
            pass  # no MX record - fall through to check A/AAAA below
        except Exception:
            return True  # DNS unreachable/misconfigured - don't block signup
    try:
        socket.setdefaulttimeout(_DNS_TIMEOUT_SECONDS)
        socket.getaddrinfo(domain, None)
        return True
    except socket.gaierror:
        return False
    except OSError:
        return True
    finally:
        socket.setdefaulttimeout(None)


def validate_email(email):
    """Returns (is_valid, error_message_or_None)."""
    email = (email or "").strip().lower()
    if not EMAIL_RE.match(email):
        return False, "That email doesn't look right. Check it and try again."
    domain = email.rsplit("@", 1)[-1]
    if domain in _DISPOSABLE_DOMAINS:
        return False, "Please use a permanent email address, not a disposable one."
    if not _domain_accepts_mail(domain):
        return False, "That email's domain doesn't seem to exist. Double check for a typo."
    return True, None
