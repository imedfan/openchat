"""
Тесты криптографии:
  1. Keygen
  2. Shared secret симметричен (Alice→Bob == Bob→Alice)
  3. Encrypt/Decrypt roundtrip
  4. Неверный ключ → ошибка расшифровки
"""

import pytest
from common.crypto import generate_keypair, load_public_key, derive_shared_key, encrypt_message, decrypt_message


def test_keypair_generation():
    priv, pub_pem = generate_keypair()
    assert priv is not None
    assert pub_pem is not None
    assert b"BEGIN PUBLIC KEY" in pub_pem


def test_shared_secret_symmetry():
    alice_priv, alice_pub = generate_keypair()
    bob_priv, bob_pub = generate_keypair()

    alice_pub_obj = load_public_key(alice_pub)
    bob_pub_obj = load_public_key(bob_pub)

    shared_alice = derive_shared_key(alice_priv, bob_pub_obj)
    shared_bob = derive_shared_key(bob_priv, alice_pub_obj)

    assert shared_alice == shared_bob, "Shared secrets must be symmetric"


def test_encrypt_decrypt_roundtrip():
    alice_priv, alice_pub = generate_keypair()
    bob_priv, bob_pub = generate_keypair()

    bob_pub_obj = load_public_key(bob_pub)
    aes_key = derive_shared_key(alice_priv, bob_pub_obj)

    plaintext = "Привет, это секретное сообщение!"
    ct_b64, nonce_b64 = encrypt_message(plaintext, aes_key)

    # Bob decrypt
    alice_pub_obj = load_public_key(alice_pub)
    aes_key_bob = derive_shared_key(bob_priv, alice_pub_obj)

    decrypted = decrypt_message(ct_b64, nonce_b64, aes_key_bob)
    assert decrypted == plaintext


def test_wrong_key_fails():
    alice_priv, alice_pub = generate_keypair()
    bob_priv, bob_pub = generate_keypair()

    bob_pub_obj = load_public_key(bob_pub)
    aes_key = derive_shared_key(alice_priv, bob_pub_obj)

    plaintext = "Secret"
    ct_b64, nonce_b64 = encrypt_message(plaintext, aes_key)

    # Eve tries to decrypt with her own key
    eve_priv, eve_pub = generate_keypair()
    eve_pub_obj = load_public_key(eve_pub)
    eve_key = derive_shared_key(eve_priv, eve_pub_obj)  # self-exchange, wrong key

    with pytest.raises(Exception):
        decrypt_message(ct_b64, nonce_b64, eve_key)
