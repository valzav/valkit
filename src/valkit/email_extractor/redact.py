"""Replace secrets and wallet addresses with numbered placeholders.

Provider token patterns follow the gitleaks default rules (github.com/gitleaks/gitleaks,
config/gitleaks.toml), Copyright (c) 2019 Zachary Rice, MIT; see THIRD_PARTY_NOTICES.
Address formats follow the chains' own specs: bech32 lengths from BIP173, seed-phrase words
from the BIP39 English wordlist.
"""

import re
from collections import defaultdict
from collections.abc import Callable
from typing import cast

from mnemonic import Mnemonic  # pyright: ignore[reportMissingTypeStubs]

BASE58 = "1-9A-HJ-NP-Za-km-z"
# Hashes such as git commit IDs are hex, and hex digits are also valid base58. Wallet
# addresses are never pure hex, so a base58 match must contain a non-hex character.
NOT_HEX = rf"(?=[{BASE58}]*[g-zG-Z])"
# Characters that end a bare value; keeps JSON quotes and Markdown syntax intact.
VALUE = r"[^\s\"'`,;<>()\[\]*]+"
KEYWORD = r"(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|access[_-]?token)"

# Order matters: specific formats run before the broad wallet patterns that could overlap them.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "private-key",
        re.compile(
            r"-----BEGIN[ A-Z0-9_-]*PRIVATE KEY(?: BLOCK)?-----[\s\S]*?-----END[ A-Z0-9_-]*"
            r"PRIVATE KEY(?: BLOCK)?-----"
        ),
    ),
    ("aws-key", re.compile(r"\b(?:A3T[A-Z0-9]|AKIA|ASIA|ABIA|ACCA)[A-Z2-7]{16}\b")),
    ("github-token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[0-9a-zA-Z]{36}\b")),
    ("github-token", re.compile(r"\bgithub_pat_\w{82}\b")),
    ("gitlab-token", re.compile(r"\bglpat-[\w-]{20}")),
    ("anthropic-key", re.compile(r"\bsk-ant-(?:api03|admin01)-[a-zA-Z0-9_-]{93}AA")),
    (
        "openai-key",
        re.compile(
            r"\bsk-(?:proj|svcacct|admin)-(?:[A-Za-z0-9_-]{74}|[A-Za-z0-9_-]{58})T3BlbkFJ"
            r"(?:[A-Za-z0-9_-]{74}|[A-Za-z0-9_-]{58})\b|\bsk-[a-zA-Z0-9]{20}T3BlbkFJ[a-zA-Z0-9]{20}"
        ),
    ),
    ("stripe-key", re.compile(r"\b(?:sk|rk)_(?:test|live|prod)_[a-zA-Z0-9]{10,99}\b")),
    ("slack-token", re.compile(r"\bxoxb-[0-9]{10,13}-[0-9]{10,13}[a-zA-Z0-9-]*")),
    ("slack-token", re.compile(r"\bxox[pe](?:-[0-9]{10,13}){3}-[a-zA-Z0-9-]{28,34}")),
    ("slack-token", re.compile(r"(?i)\bxapp-\d-[A-Z0-9]+-\d+-[a-z0-9]+")),
    ("google-key", re.compile(r"\bAIza[\w-]{35}(?![\w-])")),
    (
        "jwt",
        re.compile(
            r"\bey[a-zA-Z0-9]{17,}\.ey[a-zA-Z0-9/\\_-]{17,}\.(?:[a-zA-Z0-9/\\_-]{10,}={0,2})?"
        ),
    ),
    ("eth-address", re.compile(r"\b0x[0-9a-fA-F]{40}\b")),
    # 32 bytes in hex: an Ethereum private key (also catches transaction hashes, which is harmless).
    ("hex-key", re.compile(r"(?<![0-9a-fA-F])(?:0x)?[0-9a-fA-F]{64}(?![0-9a-fA-F])")),
    ("btc-address", re.compile(r"\bbc1[ac-hj-np-z02-9]{11,71}\b")),
    (
        "btc-address",
        re.compile(rf"(?<![{BASE58}])(?=[13]){NOT_HEX}[13][{BASE58}]{{25,34}}(?![{BASE58}])"),
    ),
    ("tron-address", re.compile(rf"(?<![{BASE58}])T[{BASE58}]{{33}}(?![{BASE58}])")),
    (
        "solana-address",
        re.compile(rf"(?<![{BASE58}])(?=[{BASE58}]*\d){NOT_HEX}[{BASE58}]{{32,44}}(?![{BASE58}])"),
    ),
]
KEYWORD_VALUE_RE = re.compile(rf"(?i)\b{KEYWORD}\b[*_]*\s*[:=]\s*[*_]*(?P<value>{VALUE})")
URL_PASSWORD_RE = re.compile(r"(?<=://)[^/\s:@]+:(?P<value>[^/\s@]+)@")
QUERY_SECRET_RE = re.compile(rf"(?i)[?&][\w-]*{KEYWORD}[\w-]*=(?P<value>[^&\s)#\"]+)")
WORD_RE = re.compile(r"[A-Za-z]+")
SEED_GAP_RE = re.compile(r"[\s,;.:()\d-]*")


def placeholder(label: str) -> str:
    """Placeholders render as inline code, so they stand out from the text in Markdown viewers."""
    return f"`[{label}]`"


REDACTED_PREFIX = placeholder("REDACTED:").removesuffix("]`")
# BIP39 mnemonics are 12 to 24 words; shorter runs of wordlist words are ordinary prose.
SEED_MIN_WORDS = 12


class Redactor:
    def __init__(self) -> None:
        self._placeholders: dict[str, str] = {}
        self._counts: defaultdict[str, int] = defaultdict(int)
        self._wordlist = frozenset(Mnemonic("english").wordlist)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]

    def placeholder_for(self, kind: str, value: str) -> str:
        if value not in self._placeholders:
            self._counts[kind] += 1
            self._placeholders[value] = placeholder(f"REDACTED:{kind}-{self._counts[kind]}")
        return self._placeholders[value]

    def redact_data(self, data: object) -> object:
        """Redact every string inside JSON-like data, so the result still serialises cleanly."""
        if isinstance(data, str):
            return self.redact(data)
        if isinstance(data, dict):
            items = cast(dict[object, object], data).items()
            return {key: self.redact_data(value) for key, value in items}
        if isinstance(data, list):
            return [self.redact_data(value) for value in cast(list[object], data)]
        return data

    def redact(self, text: str) -> str:
        for kind, pattern in PATTERNS:
            text = pattern.sub(lambda m, k=kind: self.placeholder_for(k, m.group(0)), text)
        text = self._redact_group(text, URL_PASSWORD_RE, "password")
        text = self._redact_group(text, QUERY_SECRET_RE, "secret")
        text = self._redact_group(text, KEYWORD_VALUE_RE, "secret", _looks_secret)
        return self._redact_seed_phrases(text)

    def _redact_group(
        self,
        text: str,
        pattern: re.Pattern[str],
        kind: str,
        accept: Callable[[str], bool] = lambda _: True,
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            value = match.group("value")
            # An earlier pattern may already have replaced this value.
            if value.startswith(REDACTED_PREFIX) or not accept(value):
                return match.group(0)
            start, end = match.span("value")
            whole = match.group(0)
            offset = match.start()
            return (
                whole[: start - offset] + self.placeholder_for(kind, value) + whole[end - offset :]
            )

        return pattern.sub(replace, text)

    def _redact_seed_phrases(self, text: str) -> str:
        runs: list[tuple[int, int]] = []
        run: list[re.Match[str]] = []
        for word in WORD_RE.finditer(text):
            joined = run and SEED_GAP_RE.fullmatch(text, run[-1].end(), word.start())
            if word.group(0).lower() in self._wordlist:
                run = [*run, word] if joined else [word]
            else:
                run = []
            if len(run) >= SEED_MIN_WORDS:
                if runs and runs[-1][0] == run[0].start():
                    runs[-1] = (run[0].start(), run[-1].end())
                else:
                    runs.append((run[0].start(), run[-1].end()))
        for start, end in reversed(runs):
            text = text[:start] + self.placeholder_for("seed-phrase", text[start:end]) + text[end:]
        return text


def _looks_secret(value: str) -> bool:
    """Skip plain words after a keyword ("Token: ETH", "secret: focus").

    Secrets mix in digits or symbols.
    """
    # Ignore sentence punctuation, so "secret: focus." reads as the plain word "focus".
    return bool(re.search(r"[\d\W_]", value.rstrip(".!?:")))


def redact(text: str) -> str:
    return Redactor().redact(text)
