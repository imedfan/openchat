"""
Интеграционный тест E2EE:
  1. Сервер запускается
  2. Два клиента подключаются
  3. Обмениваются публичными ключами через participants
  4. Отправляют DM (encrypted)
  5. Проверяют что сервер НЕ видит plaintext
"""

import asyncio
import json
import base64

import websockets

from common.crypto import generate_keypair, load_public_key, derive_shared_key, encrypt_message, decrypt_message
from common.protocol import MSG_CONNECT, MSG_CONNECTED, MSG_DIRECT, MSG_PARTICIPANTS, make_connect


SERVER_URI = "ws://127.0.0.1:5000"


async def test_e2e_dm():
    # ── Client 1 connects ──
    c1 = await websockets.connect(SERVER_URI)
    c1_priv, c1_pub = generate_keypair()
    await c1.send(make_connect("Alice", c1_pub))
    r1 = json.loads(await c1.recv())
    assert r1["type"] == MSG_CONNECTED
    c1_id = r1["client_id"]

    # Получаем participants от сервера
    p1 = json.loads(await c1.recv())
    assert p1["type"] == MSG_PARTICIPANTS

    await asyncio.sleep(0.5)

    # ── Client 2 connects ──
    c2 = await websockets.connect(SERVER_URI)
    c2_priv, c2_pub = generate_keypair()
    await c2.send(make_connect("Bob", c2_pub))
    r2 = json.loads(await c2.recv())
    assert r2["type"] == MSG_CONNECTED
    c2_id = r2["client_id"]

    p2 = json.loads(await c2.recv())
    assert p2["type"] == MSG_PARTICIPANTS

    # Alice получает participants с Bob
    msgs = []
    for _ in range(3):
        try:
            m = await asyncio.wait_for(c1.recv(), timeout=1)
            msgs.append(json.loads(m))
        except asyncio.TimeoutError:
            break

    # Находим participants message с публичным ключом Bob
    participants_msg = None
    for m in msgs:
        if m["type"] == MSG_PARTICIPANTS:
            participants_msg = m
            break
    assert participants_msg is not None, f"Alice didn't receive participants update. Got: {msgs}"

    # Находим Bob в participants
    bob_info = None
    for p in participants_msg["participants"]:
        if p["client_id"] == c2_id:
            bob_info = p
            break
    assert bob_info is not None, f"Bob not found in participants: {participants_msg}"
    bob_pub_pem = bob_info["public_key"].encode("utf-8")

    # ── Alice encrypts DM for Bob ──
    bob_pub_obj = load_public_key(bob_pub_pem)
    aes_key = derive_shared_key(c1_priv, bob_pub_obj)

    plaintext = "Привет Боб, это секретное сообщение!"
    ct_b64, nonce_b64 = encrypt_message(plaintext, aes_key)

    # ── Alice sends encrypted DM ──
    dm_payload = json.dumps({
        "type": MSG_DIRECT,
        "client_id": c1_id,
        "username": "Alice",
        "target_id": c2_id,
        "content": ct_b64,
        "nonce": nonce_b64,
        "message_id": "test_dm_1",
    })
    await c1.send(dm_payload)

    # ── Bob receives encrypted DM ──
    received = json.loads(await asyncio.wait_for(c2.recv(), timeout=2))
    assert received["type"] == MSG_DIRECT, f"Bob expected direct msg, got: {received}"
    received_ct = received["content"]
    received_nonce = received["nonce"]

    # ── Bob decrypts ──
    alice_pub_obj = load_public_key(c1_pub)
    aes_key_bob = derive_shared_key(c2_priv, alice_pub_obj)
    decrypted = decrypt_message(received_ct, received_nonce, aes_key_bob)

    assert decrypted == plaintext, f"Decrypted text doesn't match. Got: {decrypted}"

    # ── Verify server sees only ciphertext ──
    # Сервер ретранслирует ct_b64, он НЕ знает plaintext
    assert received_ct == ct_b64, "Server should relay ciphertext as-is"
    assert received_ct != plaintext, "Server must NOT see plaintext"

    print("\n✓ E2E DM test PASSED — shared key derived, message encrypted/decrypted, server sees only ciphertext")

    c1.close()
    c2.close()


if __name__ == "__main__":
    asyncio.run(test_e2e_dm())
