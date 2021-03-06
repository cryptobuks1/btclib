#!/usr/bin/env python3

# Copyright (C) 2017-2020 The btclib developers
#
# This file is part of btclib. It is subject to the license terms in the
# LICENSE file found in the top-level directory of this distribution.
#
# No part of btclib including this file, may be copied, modified, propagated,
# or distributed except according to the terms contained in the LICENSE file.

"""ScriptPubKey functions.

"""

from typing import Dict, List, Optional, Sequence, Tuple, Union

from .alias import Key, Octets, Script, String, Token
from .hashes import (hash160_from_pubkey, hash160_from_script,
                     hash256_from_script)
from .network import p2pkh_prefix_from_network, p2sh_prefix_from_network
from .script import decode, encode
from .to_pubkey import bytes_from_key
from .utils import bytes_from_octets

# 1. Hash/WitnessProgram from pubkey/script

# hash160_from_pubkey, hash160_from_script, and hash256_from_script
# are imported from base58address


# 2. scriptPubKey from Hash/WitnessProgram and vice versa


def scriptPubKey_from_payload(s_type: str,
                              payloads: Union[Octets, List[Octets]],
                              m: int = 0,
                              lexicographic_sort: bool = True) -> bytes:
    "Return the requested scriptPubKey for the provided payload."

    script_type = s_type.lower()

    if (script_type == "p2ms") ^ (m != 0):
        errmsg = f"Invalid m ({m}) for {script_type} script"
        raise ValueError(errmsg)

    if isinstance(payloads, list):
        if script_type == "p2ms":
            if m < 1 or m > 16:
                raise ValueError(
                    f"Invalid m ({m}) in m-of-n multisignature")
            if lexicographic_sort:
                payloads = sorted(payloads)
            n = len(payloads)
            if n < m or n > 16:
                raise ValueError(
                    f"Invalid n ({n}) in {m}-of-{n} multisignature")
            script: List[Token] = [m]
            for key in payloads:
                key = bytes_from_octets(key, (33, 65))
                script.append(key)
            script.append(n)
            script.append('OP_CHECKMULTISIG')
        else:
            errmsg = f"Invalid list of Octets for {script_type} script"
            raise ValueError(errmsg)
    else:
        if script_type == 'nulldata':
            payload = bytes_from_octets(payloads)
            if len(payload) > 80:
                msg = f"Invalid data lenght ({len(payload)} bytes) "
                msg += "for nulldata scriptPubKey"
                raise ValueError(msg)
            script = ['OP_RETURN', payload]
        elif script_type == 'p2pk':
            payload = bytes_from_octets(payloads, (33, 65))
            script = [payload, 'OP_CHECKSIG']
        elif script_type == 'p2wsh':
            payload = bytes_from_octets(payloads, 32)
            script = [0, payload]
        elif script_type == 'p2pkh':
            payload = bytes_from_octets(payloads, 20)
            script = ['OP_DUP', 'OP_HASH160', payload,
                      'OP_EQUALVERIFY', 'OP_CHECKSIG']
        elif script_type == 'p2sh':
            payload = bytes_from_octets(payloads, 20)
            script = ['OP_HASH160', payload, 'OP_EQUAL']
        elif script_type == 'p2wpkh':
            payload = bytes_from_octets(payloads, 20)
            script = [0, payload]
        else:
            raise ValueError(f'Unknown script type: {script_type}')

    return encode(script)


def payload_from_scriptPubKey(script: Script) -> Tuple[str, Union[bytes, List[bytes]], int]:
    "Return (scriptPubKey type, payload, m) from the input script."

    if isinstance(script, list):
        s = encode(script)
    else:
        s = bytes_from_octets(script)

    l = len(s)
    if l == s[0] + 2 and s[0] in (0x41, 0x21) and s[-1] == 0xAC:          # pk
        # p2pk [pubkey, OP_CHECKSIG]
        # 0x41{65-byte pubkey}AC or 0x21{33-byte pubkey}AC
        return 'p2pk', s[1:-1], 0
    elif s[-1] == 0xAE:                                                   # ms
        # p2ms [m, pubkeys, n, OP_CHECKMULTISIG]
        script = decode(s)
        m = int(script[0])
        if m < 1 or m > 16:
            raise ValueError(
                f"Invalid m ({m}) in {m}-of-n multisignature")
        n = len(script) - 3
        if n < m or n > 16:
            raise ValueError(
                f"Invalid n ({n}) in {m}-of-{n} multisignature")
        if n != int(script[-2]):
            errmsg = f"Keys ({n}) / n ({int(script[-2])}) mismatch "
            errmsg += "in m-of-n multisignature"
            raise ValueError(errmsg)
        keys: List[bytes] = []
        for pk in script[1:-2]:
            if isinstance(pk, int):
                raise ValueError(f"Invalid key in p2ms")
            key = bytes_from_octets(pk, (33, 65))
            keys.append(key)
        return 'p2ms', keys, m
    elif l <= 83 and s[0] == 0x6A:                                   # nulldata
        # nulldata [OP_RETURN, data]
        zeroone = int(l > 77)
        if s[1 + zeroone] != l - 2 - zeroone:
            errmsg = f"Wrong data lenght ({s[1+zeroone]}) in {l}-bytes "
            errmsg += f"nulldata script: it should have been {l-2-zeroone}"
            errmsg += f": {decode(s)}"
            raise ValueError(errmsg)
        if l < 77:
            # OP_RETURN, data length, data up to 74 bytes max
            # 0x6A{1 byte data-length}{data (0-74 bytes)}
            return 'nulldata', s[2:], 0
        if l > 77:
            # OP_RETURN, OP_PUSHDATA1, data length, data min 75 bytes up to 80
            # 0x6A4C{1-byte data-length}{data (75-80 bytes)}
            if s[1] != 0x4c:
                errmsg = f"Missing OP_PUSHDATA1 (0x4c) in {l}-bytes nulldata script"
                errmsg += f", got {hex(s[1])} instead"
                errmsg += f": {decode(s)}"
                raise ValueError(errmsg)
            return 'nulldata', s[3:], 0
        raise ValueError(f"Invalid 77 bytes OP_RETURN script length")
    elif l == 25 and s[:3] == b'\x76\xa9\x14' and s[-2:] == b'\x88\xac':  # pkh
        # p2pkh [OP_DUP, OP_HASH160, pubkey_hash, OP_EQUALVERIFY, OP_CHECKSIG]
        # 0x76A914{20-byte pubkey_hash}88AC
        return 'p2pkh', s[3:l - 2], 0
    elif l == 23 and s[:2] == b'\xa9\x14' and s[-1] == 0x87:              # sh
        # p2sh [OP_HASH160, script_hash, OP_EQUAL]
        # 0xA914{20-byte script_hash}87
        return 'p2sh', s[2:l - 1], 0
    elif l == 22 and s[:2] == b'\x00\x14':                                # wkh
        # p2wpkh [0, pubkey_hash]
        # 0x0014{20-byte pubkey_hash}
        return 'p2wpkh', s[2:], 0
    elif l == 34 and s[:2] == b'\x00\x20':                                # wsh
        # p2wsh [0, script_hash]
        # 0x0020{32-byte script_hash}
        return 'p2wsh', s[2:], 0
    else:
        errmsg = f"Unknown {len(s)}-bytes script"
        errmsg += f", starts with {s[:3].hex()}"
        errmsg += f", ends with {s[-2:].hex()}"
        errmsg += f": {decode(s)}"
        raise ValueError(errmsg)

# 1.+2. = 3. scriptPubKey from pubkey/script


def p2pk(key: Key) -> bytes:
    "Return the p2pk scriptPubKey of the provided pubkey."

    payload, _ = bytes_from_key(key)
    return scriptPubKey_from_payload('p2pk', payload)


def p2ms(keys: List[Key], m: int, lexicographic_sort: bool = True,
         compressed: Optional[bool] = None) -> bytes:
    "Return the m-of-n multi-sig scriptPubKey of the provided pubkeys."

    pk: List[Octets] = [
        bytes_from_key(p, compressed=compressed)[0] for p in keys]
    return scriptPubKey_from_payload('p2ms', pk, m, lexicographic_sort)


def nulldata(data: String) -> bytes:
    "Return the nulldata scriptPubKey of the provided data."

    if isinstance(data, str):
        data = data.encode()
    return scriptPubKey_from_payload('nulldata', data)


def p2pkh(key: Key, compressed: Optional[bool] = None) -> bytes:
    "Return the p2pkh scriptPubKey of the provided pubkey."

    pubkey_h160, _ = hash160_from_pubkey(key, compressed=compressed)
    return scriptPubKey_from_payload('p2pkh', pubkey_h160)


def p2sh(script: Script) -> bytes:
    "Return the p2sh scriptPubKey of the provided script."

    script_h160 = hash160_from_script(script)
    return scriptPubKey_from_payload('p2sh', script_h160)


def p2wpkh(key: Key) -> bytes:
    "Return the p2wpkh scriptPubKey of the provided pubkey."
    compressed = True  # needed to force check on pubkey
    pubkey_h160, _ = hash160_from_pubkey(key, compressed=compressed)
    return scriptPubKey_from_payload('p2wpkh', pubkey_h160)


def p2wsh(wscript: Script) -> bytes:
    "Return the p2wsh scriptPubKey of the provided script."

    script_h256 = hash256_from_script(wscript)
    return scriptPubKey_from_payload('p2wsh', script_h256)
