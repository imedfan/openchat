"""
E2EE криптография для Direct Messages.

Протокол:
  1. Каждый клиент генерирует ECDH keypair (SECP256R1) при старте.
  2. Публичные ключи обмениваются через participants list.
  3. Shared secret = ECDH(my_private, their_public).
  4. AES-256-GCM ключ = HKDF(shared_secret, info=b"openchat_dm").
  5. DM шифруется AES-GCM, nonce + ciphertext передаются в JSON (base64).
"""

import base64
import os
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def generate_keypair():
    """
    Генерирует ECDH keypair на SECP256R1.
    Возвращает (private_key_obj, public_key_pem_bytes).
    Приватный ключ хранится ТОЛЬКО в памяти.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_key, public_key_pem


def load_public_key(pem_bytes: bytes):
    """Загружает публичный ключ из PEM."""
    return serialization.load_pem_public_key(pem_bytes)


def derive_shared_key(my_private, their_public) -> bytes:
    """
    ECDH → shared secret → HKDF → 256-bit AES key.
    Возвращает 32-байтовый ключ для AES-256-GCM.
    """
    shared_secret = my_private.exchange(ec.ECDH(), their_public)

    derived_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"openchat_dm",
    ).derive(shared_secret)

    return derived_key


def encrypt_message(plaintext: str, aes_key: bytes) -> tuple[str, str]:
    """
    Шифрует plaintext через AES-256-GCM.
    Возвращает (ciphertext_b64, nonce_b64).
    """
    nonce = os.urandom(12)  # 96-bit nonce для GCM
    aesgcm = AESGCM(aes_key)
    ciphertext = aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
    return base64.b64encode(ciphertext).decode(), base64.b64encode(nonce).decode()


def decrypt_message(ciphertext_b64: str, nonce_b64: str, aes_key: bytes) -> str:
    """
    Расшифровывает AES-256-GCM ciphertext.
    Возвращает plaintext string.
    Бросает exception если authentication tag не совпадает.
    """
    ciphertext = base64.b64decode(ciphertext_b64)
    nonce = base64.b64decode(nonce_b64)
    aesgcm = AESGCM(aes_key)
    plaintext = aesgcm.decrypt(nonce, ciphertext, None)
    return plaintext.decode("utf-8")
