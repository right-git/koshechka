import os
import hashlib
import io
import ipaddress
import os
from re import A
import struct
import cryptg

from base64 import urlsafe_b64encode
from telethon.sync import TelegramClient as TelethonClient
from telethon.sessions import StringSession, SQLiteSession
from loguru import logger
from opentele.tl import TelegramClient as OpenTeleClient
from opentele.api import UseCurrentSession, API


class QDataStream:
    def __init__(self, data):
        self.stream = io.BytesIO(data)

    def read(self, n=None):
        if n < 0:
            n = 0
        data = self.stream.read(n)
        if n != 0 and len(data) == 0:
            return None
        if n is not None and len(data) != n:
            raise Exception("unexpected eof")
        return data

    def read_buffer(self):
        length_bytes = self.read(4)
        if length_bytes is None:
            return None
        length = int.from_bytes(length_bytes, "big", signed=True)
        data = self.read(length)
        if data is None:
            raise Exception("unexpected eof")
        return data

    def read_uint32(self):
        data = self.read(4)
        if data is None:
            return None
        return int.from_bytes(data, "big")

    def read_uint64(self):
        data = self.read(8)
        if data is None:
            return None
        return int.from_bytes(data, "big")

    def read_int32(self):
        data = self.read(4)
        if data is None:
            return None
        return int.from_bytes(data, "big", signed=True)


class TGConverter:
    def __init__(self, api_id, api_hash):
        """
        :param api_id: The API ID you obtained from https://my.telegram.org
        :param api_hash: The API hash you obtained from https://my.telegram.org
        :cvar dc_tables: Maps data center IDs to (address, port) tuples.
        """
        self.api_id = api_id
        self.api_hash = api_hash
        self.dc_tables = {
            1: ("149.154.175.50", 443),
            2: ("149.154.167.51", 443),
            3: ("149.154.175.100", 443),
            4: ("149.154.167.91", 443),
            5: ("149.154.171.5", 443),
        }

    def _create_local_key(self, passcode, salt):
        if passcode:
            iterations = 100_000
        else:
            iterations = 1
        _hash = hashlib.sha512(salt + passcode + salt).digest()
        return hashlib.pbkdf2_hmac("sha512", _hash, salt, iterations, 256)

    def _prepare_aes_oldmtp(self, auth_key, msg_key, send):
        if send:
            x = 0
        else:
            x = 8

        sha1 = hashlib.sha1()
        sha1.update(msg_key)
        sha1.update(auth_key[x:][:32])
        a = sha1.digest()

        sha1 = hashlib.sha1()
        sha1.update(auth_key[32 + x :][:16])
        sha1.update(msg_key)
        sha1.update(auth_key[48 + x :][:16])
        b = sha1.digest()

        sha1 = hashlib.sha1()
        sha1.update(auth_key[64 + x :][:32])
        sha1.update(msg_key)
        c = sha1.digest()

        sha1 = hashlib.sha1()
        sha1.update(msg_key)
        sha1.update(auth_key[96 + x :][:32])
        d = sha1.digest()

        key = a[:8] + b[8:] + c[4:16]
        iv = a[8:] + b[:8] + c[16:] + d[:8]
        return key, iv

    def _aes_decrypt_local(self, ciphertext, auth_key, key_128):
        key, iv = self._prepare_aes_oldmtp(auth_key, key_128, False)
        return cryptg.decrypt_ige(ciphertext, key, iv)

    def _decrypt_local(self, data, key):
        encrypted_key = data[:16]
        data = self._aes_decrypt_local(data[16:], key, encrypted_key)
        sha1 = hashlib.sha1()
        sha1.update(data)
        if encrypted_key != sha1.digest()[:16]:
            raise Exception("failed to decrypt")
        length = int.from_bytes(data[:4], "little")
        data = data[4:length]
        return QDataStream(data)

    def _read_file(self, name):
        with open(name, "rb") as f:
            magic = f.read(4)
            if magic != b"TDF$":
                raise Exception("invalid magic")
            version_bytes = f.read(4)
            data = f.read()
        data, digest = data[:-16], data[-16:]
        data_len_bytes = len(data).to_bytes(4, "little")
        md5 = hashlib.md5()
        md5.update(data)
        md5.update(data_len_bytes)
        md5.update(version_bytes)
        md5.update(magic)
        digest = md5.digest()
        if md5.digest() != digest:
            raise Exception("invalid digest")
        return QDataStream(data)

    def _read_encrypted_file(self, name, key):
        stream = self._read_file(name)
        encrypted_data = stream.read_buffer()
        return self._decrypt_local(encrypted_data, key)

    def _account_data_string(self, index=0):
        s = "data"
        if index > 0:
            s += f"#{index+1}"
        md5 = hashlib.md5()
        md5.update(bytes(s, "utf-8"))
        digest = md5.digest()
        return digest[:8][::-1].hex().upper()[::-1]

    def _read_user_auth(self, directory, local_key, index=0):
        name = self._account_data_string(index)
        path = os.path.join(directory, f"{name}s")
        stream = self._read_encrypted_file(path, local_key)
        if stream.read_uint32() != 0x4B:
            raise Exception("unsupported user auth config")
        stream = QDataStream(stream.read_buffer())
        user_id = stream.read_uint32()
        main_dc = stream.read_uint32()
        if user_id == 0xFFFFFFFF and main_dc == 0xFFFFFFFF:
            user_id = stream.read_uint64()
            main_dc = stream.read_uint32()
        if main_dc not in self.dc_tables:
            raise Exception(f"unsupported main dc: {main_dc}")
        length = stream.read_uint32()
        for _ in range(length):
            auth_dc = stream.read_uint32()
            auth_key = stream.read(256)
            if auth_dc == main_dc:
                return auth_dc, auth_key
        raise Exception("invalid user auth config")

    def _build_session(self, dc, ip, port, key):
        ip_bytes = ipaddress.ip_address(ip).packed
        data = struct.pack(">B4sH256s", dc, ip_bytes, port, key)
        encoded_data = urlsafe_b64encode(data).decode("ascii")
        return "1" + encoded_data

    async def tdata_to_string(self, path: str):
        """
        Converts Telegram TDATA files into string session.

        This function reads a specified TDATA path and extracts session
        information by decrypting key data and user authentication details.
        It returns a list of session strings encoded for use with Telegram.

        :param path: The file path to the Telegram TDATA directory.
        :return: A list of encoded session strings.

        :raises Exception: If the salt or local key has an invalid length,
                        or if user authentication configuration is unsupported.
        """
        stream = self._read_file(os.path.join(path, "key_datas"))
        salt = stream.read_buffer()
        if len(salt) != 32:
            raise Exception("invalid salt length")
        key_encrypted = stream.read_buffer()
        info_encrypted = stream.read_buffer()

        passcode_key = self._create_local_key(b"", salt)
        key_inner_data = self._decrypt_local(key_encrypted, passcode_key)
        local_key = key_inner_data.read(256)
        if len(local_key) != 256:
            raise Exception("invalid local key")

        sessions = []

        info_data = self._decrypt_local(info_encrypted, local_key)
        count = info_data.read_uint32()

        for _ in range(count):
            index = info_data.read_uint32()
            dc, key = self._read_user_auth(path, local_key, index)
            ip, port = self.dc_tables[dc]
            sessions.append(self._build_session(dc, ip, port, key))

        for str_session in sessions:
            string_session = StringSession(str_session)
            string_client = TelethonClient(
                string_session, api_hash=self.api_hash, api_id=self.api_id
            )

            try:
                await string_client.connect()
                me = await string_client.get_me()
            except Exception as err:
                raise Exception(f"Invalid session: {str_session}\nError: {err}")

            phone = me.phone
            auth_key = string_client.session.save()

            os.makedirs("string_sessions", exist_ok=True)

            with open(f"string_sessions/{phone}.txt", "w", encoding="utf-8") as f:
                f.write(auth_key)

            logger.success(f"[{phone}.txt] - Successfully created a string session")

    async def session_to_tdata(self, path: str):
        try:
            api = API.TelegramDesktop.Generate()
            client = OpenTeleClient(path, api)
            tdesk = await client.ToTDesktop(flag=UseCurrentSession, api=api)

            session_name = path.split("/")[-1].replace(".session", "")
            logger.info(f"Converting {session_name}")
            os.makedirs("tdata_converted", exist_ok=True)

            tdesk.SaveTData(f"tdata_converted/{session_name}/tdata")
            logger.success(f"[{session_name}/tdata] - Successfully created a tdata folder")
        except:
            logger.error(f"Error converting {path}")
