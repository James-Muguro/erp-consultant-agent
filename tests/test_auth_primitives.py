"""
Unit tests for the authentication security primitives introduced in the
Phase 2 auth build.

Scope: only the pure functions in src.auth.security. No HTTP requests,
no database, no service-layer behavior. Service-layer behavior
(signup, login, MFA, refresh rotation, password reset, logout) is
covered by later phases.

Coverage:
    generate_secure_token
        - produces different values across calls
        - respects the minimum entropy boundary
        - default output length is comfortable
    hash_token
        - deterministic for the same input
        - different inputs produce different digests
        - rejects empty/None input
    generate_otp
        - exact length, digits only, across the supported range
        - different values across calls
        - rejects out-of-range lengths
    hash_password / verify_password
        - round trip
        - wrong password fails
        - malformed stored hash returns False (not an exception)
    constant_time_equal
        - True for identical strings, False for different
        - False (not an exception) for non-string inputs
    create_access_token / decode_access_token
        - round trip returns the subject
        - expired token rejected
        - tampered signature rejected
        - token signed with a different secret rejected
        - token with alg:none rejected
        - fixed configured algorithm (HS256)
    _validate_algorithm
        - accepts every allowlisted algorithm
        - rejects 'none', empty, and unknown values
"""
from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone

import pytest

from src.auth.security import (
    _JWT_ALGORITHM,
    _SAFE_ALGORITHMS,
    _validate_algorithm,
    constant_time_equal,
    create_access_token,
    decode_access_token,
    generate_otp,
    generate_secure_token,
    hash_password,
    hash_token,
    verify_password,
)


# ---------------------------------------------------------------------------
# generate_secure_token
# ---------------------------------------------------------------------------
class TestGenerateSecureToken:
    def test_successive_tokens_differ(self):
        """Two calls must not collide. A collision here would be a
        catastrophic failure of the CSPRNG; the assertion is cheap."""
        seen = {generate_secure_token() for _ in range(64)}
        assert len(seen) == 64

    def test_default_length_is_adequate(self):
        """Default is 32 bytes → 43 URL-safe characters. Assert the
        character count so a change to the default that reduces entropy
        surfaces as a test failure."""
        token = generate_secure_token()
        # 32 bytes of base64url = ceil(32 * 4 / 3) = 43 characters with
        # the trailing '=' padding removed by token_urlsafe.
        assert len(token) >= 42

    def test_respects_explicit_length(self):
        """A larger explicit length produces a longer token."""
        short = generate_secure_token(nbytes=16)
        long_ = generate_secure_token(nbytes=64)
        assert len(long_) > len(short)

    def test_rejects_below_minimum(self):
        """Rejecting short requests is a security invariant: a caller
        asking for 8 bytes would silently produce a weak credential."""
        with pytest.raises(ValueError):
            generate_secure_token(nbytes=8)
        with pytest.raises(ValueError):
            generate_secure_token(nbytes=0)
        with pytest.raises(ValueError):
            generate_secure_token(nbytes=-1)

    def test_rejects_non_integer_length(self):
        with pytest.raises(ValueError):
            generate_secure_token(nbytes="32")  # type: ignore[arg-type]
        with pytest.raises(ValueError):
            generate_secure_token(nbytes=32.0)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# hash_token
# ---------------------------------------------------------------------------
class TestHashToken:
    def test_deterministic(self):
        raw = generate_secure_token()
        assert hash_token(raw) == hash_token(raw)

    def test_different_inputs_differ(self):
        a = hash_token(generate_secure_token())
        b = hash_token(generate_secure_token())
        assert a != b

    def test_output_is_hex_sha256(self):
        digest = hash_token("anything")
        assert len(digest) == 64
        assert all(c in "0123456789abcdef" for c in digest)

    def test_known_value(self):
        """Known-answer test: pin the exact SHA-256 of an input so an
        accidental change to the algorithm or encoding is caught."""
        # SHA-256("abc")
        assert hash_token("abc") == (
            "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        )

    def test_rejects_empty_and_none(self):
        with pytest.raises(ValueError):
            hash_token("")
        with pytest.raises(ValueError):
            hash_token(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# generate_otp
# ---------------------------------------------------------------------------
class TestGenerateOtp:
    @pytest.mark.parametrize("length", [4, 5, 6, 7, 8, 9, 10])
    def test_length_matches_request(self, length):
        assert len(generate_otp(length)) == length

    def test_digits_only(self):
        """Every character must be an ASCII digit. A non-digit here would
        break the frontend input validation and the service-layer
        verification, both of which assume a numeric code."""
        for _ in range(20):
            code = generate_otp(6)
            assert all(c in "0123456789" for c in code)

    def test_successive_codes_differ(self):
        """Statistical check: 64 six-digit codes should be effectively
        unique (birthday-paradox collision probability is negligible)."""
        seen = {generate_otp(6) for _ in range(64)}
        assert len(seen) > 60

    def test_zero_padded(self):
        """Leading zeros must be preserved. A code like '001234' must be
        exactly 6 characters, not '1234'."""
        # Run many times; a leading zero is expected with probability
        # ~1 - (9/10)^N. With 200 iterations the odds of never seeing a
        # leading zero are effectively zero.
        lengths = {len(generate_otp(6)) for _ in range(200)}
        assert lengths == {6}

    def test_rejects_out_of_range_lengths(self):
        with pytest.raises(ValueError):
            generate_otp(3)
        with pytest.raises(ValueError):
            generate_otp(11)
        with pytest.raises(ValueError):
            generate_otp(0)
        with pytest.raises(ValueError):
            generate_otp(-1)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    # Use a low cost factor in tests so the suite stays fast. Production
    # uses _BCRYPT_DEFAULT_ROUNDS (12); the round-trip property being
    # tested is identical at any cost.
    _TEST_ROUNDS = 4

    def test_round_trip(self):
        hashed = hash_password("correct horse battery staple", rounds=self._TEST_ROUNDS)
        assert verify_password("correct horse battery staple", hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct horse battery staple", rounds=self._TEST_ROUNDS)
        assert verify_password("wrong password", hashed) is False

    def test_hashes_differ_across_calls(self):
        """bcrypt salts each hash, so two hashes of the same password are
        different strings."""
        a = hash_password("same password", rounds=self._TEST_ROUNDS)
        b = hash_password("same password", rounds=self._TEST_ROUNDS)
        assert a != b

    def test_malformed_hash_returns_false(self):
        """A malformed stored hash must return False, not raise. Otherwise
        a corrupt row in the users table would turn login into a 500."""
        assert verify_password("any", "not-a-bcrypt-hash") is False
        assert verify_password("any", "") is False

    def test_non_string_inputs_return_false(self):
        assert verify_password(None, "x") is False  # type: ignore[arg-type]
        assert verify_password("x", None) is False  # type: ignore[arg-type]

    def test_long_password_is_truncated_at_72_bytes(self):
        """bcrypt truncates at 72 bytes; two passwords sharing the first
        72 bytes must verify as equal. This is a documented property of
        the existing implementation, not a defect introduced here."""
        base = "a" * 72
        hashed = hash_password(base + "suffix one", rounds=self._TEST_ROUNDS)
        assert verify_password(base + "suffix two", hashed) is True


# ---------------------------------------------------------------------------
# constant_time_equal
# ---------------------------------------------------------------------------
class TestConstantTimeEqual:
    def test_equal_strings(self):
        assert constant_time_equal("abc123", "abc123") is True

    def test_different_strings(self):
        assert constant_time_equal("abc123", "abc124") is False

    def test_empty_strings_equal(self):
        assert constant_time_equal("", "") is True

    def test_non_string_returns_false(self):
        assert constant_time_equal(None, "x") is False  # type: ignore[arg-type]
        assert constant_time_equal("x", None) is False  # type: ignore[arg-type]
        assert constant_time_equal(b"x", "x") is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# JWT access tokens
# ---------------------------------------------------------------------------
class TestAccessTokens:
    def test_round_trip(self):
        token = create_access_token("user-abc")
        assert decode_access_token(token) == "user-abc"

    def test_expired_token_rejected(self):
        """A token issued with a negative TTL must be rejected on decode.
        This is what a short access-token TTL relies on."""
        token = create_access_token("user-abc", expires_minutes=-1)
        assert decode_access_token(token) is None

    def test_tampered_signature_rejected(self):
        """Flipping a byte in the middle of the signature must
        invalidate the token.

        The test flips a middle character rather than the last one:
        base64url encodes the final byte with unused trailing bits, so
        flipping the final character can change only those unused bits
        and leave the decoded signature bytes unchanged. A middle
        character flips meaningful bits and reliably breaks the
        signature.
        """
        token = create_access_token("user-abc")
        parts = token.split(".")
        assert len(parts) == 3
        sig = parts[2]
        mid = len(sig) // 2
        flipped = ("A" if sig[mid] != "A" else "B")
        tampered = ".".join(parts[:2] + [sig[:mid] + flipped + sig[mid + 1:]])
        assert decode_access_token(tampered) is None

    def test_wrong_secret_rejected(self):
        """A token signed with a different secret must be rejected even
        though it has a valid shape and an unexpired exp claim."""
        import jwt as _jwt

        now = datetime.now(timezone.utc)
        payload = {
            "sub": "user-abc",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        forged = _jwt.encode(
            payload,
            "an entirely different secret that is at least 32 chars",
            algorithm="HS256",
        )
        assert decode_access_token(forged) is None

    def test_alg_none_rejected(self):
        """A token whose header declares alg:none must be rejected. The
        decode call passes `algorithms=['HS256']` to PyJWT, which refuses
        to accept an unsigned token regardless of the header's claim."""
        def _b64u(obj: dict) -> str:
            raw = json.dumps(obj, separators=(",", ":")).encode("utf-8")
            return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

        header = {"alg": "none", "typ": "JWT"}
        payload = {
            "sub": "user-abc",
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        }
        # Unsigned token: header.payload. (trailing empty signature).
        unsigned = f"{_b64u(header)}.{_b64u(payload)}."
        assert decode_access_token(unsigned) is None

    def test_empty_or_none_token_returns_none(self):
        assert decode_access_token("") is None
        assert decode_access_token(None) is None  # type: ignore[arg-type]

    def test_fixed_configured_algorithm(self):
        """The module-level algorithm is HS256 for this deployment. If
        this assertion ever fails, the JWT configuration has changed and
        the change should be deliberate and reviewed."""
        assert _JWT_ALGORITHM == "HS256"

    def test_create_rejects_empty_user_id(self):
        with pytest.raises(ValueError):
            create_access_token("")
        with pytest.raises(ValueError):
            create_access_token(None)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Algorithm validation
# ---------------------------------------------------------------------------
class TestValidateAlgorithm:
    @pytest.mark.parametrize("alg", sorted(_SAFE_ALGORITHMS))
    def test_accepts_allowlisted(self, alg):
        assert _validate_algorithm(alg) == alg

    @pytest.mark.parametrize("alg", ["HS256", "hs256", " Hs256 "])
    def test_normalizes_case_and_whitespace(self, alg):
        assert _validate_algorithm(alg) == "HS256"

    def test_rejects_none(self):
        """The single most important rejection: `alg: none` disables
        signature verification entirely."""
        with pytest.raises(RuntimeError):
            _validate_algorithm("none")
        with pytest.raises(RuntimeError):
            _validate_algorithm("NONE")
        with pytest.raises(RuntimeError):
            _validate_algorithm("None")

    def test_rejects_empty_or_missing(self):
        with pytest.raises(RuntimeError):
            _validate_algorithm("")
        with pytest.raises(RuntimeError):
            _validate_algorithm("   ")
        with pytest.raises(RuntimeError):
            _validate_algorithm(None)

    def test_rejects_unknown(self):
        with pytest.raises(RuntimeError):
            _validate_algorithm("HS999")
        with pytest.raises(RuntimeError):
            _validate_algorithm("garbage")