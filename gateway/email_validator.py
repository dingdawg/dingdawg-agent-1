from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, List, Optional, Sequence, Tuple


class EmailValidationError(ValueError):
    """Raised when an email address fails validation."""


class EmailFormatError(EmailValidationError):
    """Raised when an email has structural formatting issues."""


class EmailDomainError(EmailValidationError):
    """Raised when an email domain is invalid or blocked."""


@dataclass(frozen=True, slots=True)
class EmailPolicy:
    max_local_length: int = 64
    max_domain_length: int = 253
    max_total_length: int = 254
    allow_ip_domain: bool = False
    allow_quoted_local: bool = False
    allow_plus_addressing: bool = True
    blocked_domains: FrozenSet[str] = field(default_factory=frozenset)
    allowed_domains: FrozenSet[str] = field(default_factory=frozenset)
    blocked_tlds: FrozenSet[str] = field(default_factory=frozenset)
    require_tld: bool = True
    min_tld_length: int = 2


@dataclass(frozen=True, slots=True)
class EmailResult:
    valid: bool
    email: str
    local_part: str
    domain: str
    normalized: str
    errors: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


_ATOM_CHARS = re.compile(
    r"^[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+"
    r"(\.[a-zA-Z0-9!#$%&'*+/=?^_`{|}~-]+)*$"
)
_QUOTED_LOCAL = re.compile(r'^"([\x20-\x21\x23-\x5B\x5D-\x7E]|\\.)*"$')
_DOMAIN_LABEL = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]*[a-zA-Z0-9])?$")
_IP_DOMAIN = re.compile(
    r"^\[("
    r"(?:(?:25[0-5]|2[0-4]\d|[01]?\d\d?)\.){3}(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
    r"|IPv6:[0-9a-fA-F:.]+"
    r")\]$"
)
_DISPOSABLE_DOMAINS: FrozenSet[str] = frozenset({
    "mailinator.com", "guerrillamail.com", "tempmail.com",
    "throwaway.email", "yopmail.com", "sharklasers.com",
    "guerrillamailblock.com", "grr.la", "dispostable.com",
    "trashmail.com", "10minutemail.com", "temp-mail.org",
    "fakeinbox.com", "mailnesia.com", "maildrop.cc",
})


def _coerce_to_str(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, (bytes, bytearray)):
        try:
            return value.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise EmailFormatError(f"Cannot decode email bytes: {exc}") from exc
    if hasattr(value, "__str__"):
        return str(value)
    raise TypeError(f"Expected str, got {type(value).__name__}")


def _validate_local_part(
    local: str, policy: EmailPolicy,
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    if not local:
        errors.append("Local part is empty")
        return errors, warnings
    if len(local) > policy.max_local_length:
        errors.append(f"Local part exceeds {policy.max_local_length} characters")
    if local.startswith('"') and local.endswith('"'):
        if not policy.allow_quoted_local:
            errors.append("Quoted local parts are not allowed by policy")
        elif not _QUOTED_LOCAL.match(local):
            errors.append("Invalid quoted local part syntax")
    else:
        if not _ATOM_CHARS.match(local):
            errors.append("Local part contains invalid characters or malformed dot-atoms")
        if local.startswith(".") or local.endswith("."):
            errors.append("Local part must not start or end with a dot")
        if ".." in local:
            errors.append("Local part must not contain consecutive dots")
    if "+" in local:
        if not policy.allow_plus_addressing:
            errors.append("Plus addressing is not allowed by policy")
        else:
            warnings.append("Email uses plus addressing (subaddressing)")
    return errors, warnings


def _validate_domain(
    domain: str, policy: EmailPolicy,
) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []
    if not domain:
        errors.append("Domain is empty")
        return errors, warnings
    if len(domain) > policy.max_domain_length:
        errors.append(f"Domain exceeds {policy.max_domain_length} characters")
    if domain.startswith("[") and domain.endswith("]"):
        if not policy.allow_ip_domain:
            errors.append("IP address domains are not allowed by policy")
        elif not _IP_DOMAIN.match(domain):
            errors.append("Invalid IP address domain literal")
        return errors, warnings
    labels = domain.split(".")
    if policy.require_tld and len(labels) < 2:
        errors.append("Domain must have at least two labels (e.g. example.com)")
    tld = labels[-1] if labels else ""
    if policy.require_tld and len(tld) < policy.min_tld_length:
        errors.append(f"TLD must be at least {policy.min_tld_length} characters")
    for label in labels:
        if not label:
            errors.append("Domain contains empty label (consecutive dots)")
            break
        if len(label) > 63:
            errors.append(f"Domain label '{label}' exceeds 63 characters")
        if not _DOMAIN_LABEL.match(label):
            errors.append(
                f"Domain label '{label}' contains invalid characters "
                f"or starts/ends with a hyphen"
            )
    if tld.isdigit():
        errors.append("TLD must not be all numeric")
    lower_domain = domain.lower()
    if policy.blocked_tlds and tld.lower() in policy.blocked_tlds:
        errors.append(f"TLD '.{tld}' is blocked by policy")
    if policy.blocked_domains and lower_domain in policy.blocked_domains:
        errors.append(f"Domain '{domain}' is blocked by policy")
    if policy.allowed_domains and lower_domain not in policy.allowed_domains:
        errors.append(f"Domain '{domain}' is not in allowed domains list")
    if lower_domain in _DISPOSABLE_DOMAINS:
        warnings.append(f"Domain '{domain}' appears to be a disposable email provider")
    return errors, warnings


def _normalize_email(local: str, domain: str) -> str:
    return f"{local}@{domain.lower()}"


def validate_email(
    email: Any, *, policy: Optional[EmailPolicy] = None,
) -> EmailResult:
    policy = policy or EmailPolicy()
    raw = _coerce_to_str(email).strip()
    if not raw:
        raise EmailFormatError("Email address is empty")
    if len(raw) > policy.max_total_length:
        return EmailResult(
            valid=False, email=raw, local_part="", domain="",
            normalized="",
            errors=(f"Email exceeds {policy.max_total_length} characters",),
        )
    at_count = raw.count("@")
    if at_count == 0:
        raise EmailFormatError("Email address must contain exactly one '@' symbol")
    if at_count > 1:
        idx = raw.rfind("@")
        local, domain = raw[:idx], raw[idx + 1:]
        if not (local.startswith('"') and '"@' in raw):
            raise EmailFormatError("Email address contains multiple '@' symbols")
    else:
        local, domain = raw.split("@", 1)
    all_errors: List[str] = []
    all_warnings: List[str] = []
    local_errors, local_warnings = _validate_local_part(local, policy)
    all_errors.extend(local_errors)
    all_warnings.extend(local_warnings)
    domain_errors, domain_warnings = _validate_domain(domain, policy)
    all_errors.extend(domain_errors)
    all_warnings.extend(domain_warnings)
    normalized = _normalize_email(local, domain) if not all_errors else ""
    return EmailResult(
        valid=len(all_errors) == 0, email=raw, local_part=local,
        domain=domain, normalized=normalized,
        errors=tuple(all_errors), warnings=tuple(all_warnings),
    )


def validate_email_strict(
    email: Any, *, policy: Optional[EmailPolicy] = None,
) -> str:
    result = validate_email(email, policy=policy)
    if not result.valid:
        raise EmailValidationError(
            f"Invalid email '{result.email}': {'; '.join(result.errors)}"
        )
    return result.normalized


def validate_email_batch(
    emails: Sequence[Any], *, policy: Optional[EmailPolicy] = None,
) -> Dict[str, EmailResult]:
    if not isinstance(emails, (list, tuple, frozenset, set)):
        raise TypeError(f"Expected sequence of emails, got {type(emails).__name__}")
    results: Dict[str, EmailResult] = {}
    for raw in emails:
        key = str(raw)
        try:
            results[key] = validate_email(raw, policy=policy)
        except (TypeError, EmailFormatError) as exc:
            results[key] = EmailResult(
                valid=False, email=key, local_part="", domain="",
                normalized="", errors=(str(exc),),
            )
    return results