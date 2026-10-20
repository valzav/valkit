import pytest

from valkit.email_extractor.redact import redact

# Made-up values in each provider's published format.
SECRETS = {
    "aws-key": "AKIAIOSFODNN7EXAMPLE",
    "github-token": "ghp_" + "a1B2c3D4e5" * 3 + "F6g7H8",
    "gitlab-token": "glpat-" + "x" * 20,
    "anthropic-key": "sk-ant-api03-" + "a" * 93 + "AA",
    "openai-key": "sk-proj-" + "b" * 74 + "T3BlbkFJ" + "c" * 74,
    "stripe-key": "sk_live_" + "4eC39HqLyjWDarjtT1zdp7dc",
    "slack-token": "xoxb-1234567890-1234567890-AbCdEfGh",
    "google-key": "AIza" + "S" * 35,
    "jwt": "eyJhbGciOiJIUzI1NiJ9a.eyJzdWIiOiIxMjM0NTY3OD.SflKxwRJSMeKKF2QT4fw",
    "eth-address": "0x52908400098527886E0F7030069857D2E4169EE7",
    "hex-key": "4c0883a69102937d6231471b5dbb6204fe5129617082792ae468d01a3f362318",
    "btc-address": "bc1qar0srrr7xfkvy5l643lydnw9re59gtzzwf5mdq",
    "tron-address": "TLa2f6VPqDgRE67v1736s7bJ8Ray5wYjU7",
    "solana-address": "7EcDhSYGxXyscszYEp35KHN8vvw3svAuLKTzXwCFLtV",
    "seed-phrase": " ".join(["abandon"] * 11 + ["about"]),
    "private-key": "-----BEGIN PRIVATE KEY-----\nMIIEvQIBADANBg\n-----END PRIVATE KEY-----",
}


@pytest.mark.parametrize(("kind", "secret"), SECRETS.items())
def test_known_formats_are_redacted(kind: str, secret: str) -> None:
    result = redact(f"Here it is: {secret} done.")

    assert secret not in result
    assert f"`[REDACTED:{kind}-1]`" in result


def test_bitcoin_legacy_address() -> None:
    assert (
        redact("send to 1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa") == "send to `[REDACTED:btc-address-1]`"
    )


def test_keyword_values_and_url_credentials() -> None:
    text = (
        "password: hunter2!\n**API_KEY** = abc123\n"
        "https://admin:s3cret@db.example.com/x?access_token=tok3n&page=2"
    )
    assert redact(text) == (
        "password: `[REDACTED:secret-2]`\n**API_KEY** = `[REDACTED:secret-3]`\n"
        "https://admin:`[REDACTED:password-1]`@db.example.com/x?access_token=`[REDACTED:secret-1]`&page=2"
    )


def test_same_value_gets_same_placeholder() -> None:
    wallet = SECRETS["eth-address"]
    other = "0x" + "a" * 40
    assert redact(f"{wallet} then {other} then {wallet}") == (
        "`[REDACTED:eth-address-1]` then `[REDACTED:eth-address-2]` then `[REDACTED:eth-address-1]`"
    )


def test_ordinary_text_survives() -> None:
    text = (
        '{"emails": ["jane@example.com"], "phones": ["+1 555-0100", "707-235-0660"]}\n'
        "Token: ETH is up. Our secret: focus. Read https://www.linkedin.com/in/jane-doe-12345/\n"
        "We can access the market and build a better future for every investor around the world.\n"
        "Meeting at 10:30 on 2026-04-05, budget $1.5M, ticket ABC-1234."
    )
    assert redact(text) == text


def test_hex_hashes_are_not_wallet_addresses() -> None:
    commit = "ba571a3d8a5f9d39da442d8322bea9cf6a1dddef"
    text = f"release {commit}, query=release%3A%22{commit}%22"
    assert redact(text) == text


def test_secret_in_url_parameter_is_wrapped_once() -> None:
    token = SECRETS["github-token"]
    assert redact(f"https://example.com/?token={token}") == (
        "https://example.com/?token=`[REDACTED:github-token-1]`"
    )
