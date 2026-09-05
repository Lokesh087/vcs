import os
import json
import zlib
import difflib
import hashlib

class DeltaEncoder:
    """Encode and decode target content relative to a base object."""

    @staticmethod
    def encode(base: bytes, target: bytes) -> bytes:
        """
        Delta format:
        b'C' + 4-byte-offset + 4-byte-len: copy length bytes from base at offset
        b'I' + 4-byte-len + literal_bytes: insert literal target bytes
        """
        matcher = difflib.SequenceMatcher(None, base, target)
        out = bytearray()
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == 'equal':
                offset = i1
                length = i2 - i1
                out += b"C" + offset.to_bytes(4, "big") + length.to_bytes(4, "big")
            else:
                chunk = target[j1:j2]
                if chunk:
                    out += b"I" + len(chunk).to_bytes(4, "big") + chunk
        return bytes(out)

    @staticmethod
    def decode(base: bytes, delta: bytes) -> bytes:
        result = bytearray()
        pos = 0
        while pos < len(delta):
            op = delta[pos:pos+1]
            if op == b"C":
                offset = int.from_bytes(delta[pos+1:pos+5], "big")
                length = int.from_bytes(delta[pos+5:pos+9], "big")
                pos += 9
                result += base[offset:offset+length]
            elif op == b"I":
                length = int.from_bytes(delta[pos+1:pos+5], "big")
                pos += 5
                result += delta[pos:pos+length]
                pos += length
        return bytes(result)


class Packer:
    """Manages creation, indexing, and delta retrieval of packfiles."""

    PACK_HEADER = b"PVCPACK01"

    def __init__(self, store):
        self.store = store
        self.pack_dir = os.path.join(store.objects_dir, "pack")
        os.makedirs(self.pack_dir, exist_ok=True)
        self.index_file = os.path.join(self.pack_dir, "pack-index.json")
        self.store.set_packer(self)

    def _load_index(self) -> dict:
        if os.path.exists(self.index_file):
            with open(self.index_file, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _save_index(self, index: dict):
        with open(self.index_file, "w", encoding="utf-8") as f:
            json.dump(index, f, indent=2)

    def pack_objects(self, shas: list) -> str:
        """Pack loose objects into a packfile with delta compression."""
        index = self._load_index()
        entries = []
        raw_cache = {}

        for sha in sorted(shas):
            try:
                data = self.store.read_raw(sha)
            except KeyError:
                continue
            obj_type, body = data.split(b"\n", 1)
            raw_cache[sha] = (obj_type, body, data)

            delta_base_sha = None
            delta_bytes = None

            for prev in reversed(entries[-30:]):
                prev_type, prev_body, _ = raw_cache[prev["sha"]]
                if prev_type != obj_type or prev["is_delta"]:
                    continue
                candidate = DeltaEncoder.encode(prev_body, body)
                if len(candidate) < len(body) * 0.8:
                    delta_base_sha = prev["sha"]
                    delta_bytes = candidate
                    break

            entries.append({
                "sha": sha,
                "type": obj_type.decode("utf-8"),
                "size": len(delta_bytes if delta_bytes is not None else body),
                "is_delta": delta_bytes is not None,
                "base": delta_base_sha,
                "_delta": delta_bytes,
                "_body": body,
                "_full": data
            })

        if not entries:
            return ""

        pack_name = f"pack-{hashlib.sha256(b''.join(e['sha'].encode() for e in entries)).hexdigest()[:12]}.vcp"
        pack_path = os.path.join(self.pack_dir, pack_name)

        payload = bytearray(self.PACK_HEADER)
        offsets = {}

        for e in entries:
            offsets[e["sha"]] = len(payload)
            if e["is_delta"]:
                content = zlib.compress(e["_delta"])
            else:
                content = zlib.compress(e["_full"])
            payload += len(content).to_bytes(4, "big") + content

        with open(pack_path, "wb") as f:
            f.write(payload)

        new_index = {}
        for e in entries:
            new_index[e["sha"]] = {
                "pack": pack_name,
                "offset": offsets[e["sha"]],
                "type": e["type"],
                "is_delta": e["is_delta"],
                "base": e["base"]
            }
            self.store.remove_loose(e["sha"])

        index.update(new_index)
        self._save_index(index)
        return pack_name

    def read_object(self, sha: str) -> bytes:
        """Read object from packfile, reconstructing delta chain if necessary."""
        index = self._load_index()
        if sha not in index:
            raise KeyError(f"Object {sha} not found in packfiles.")

        chain = []
        curr = sha
        while True:
            info = index[curr]
            chain.append(info)
            if not info["is_delta"]:
                break
            curr = info["base"]

        # Base is last element in chain
        base_info = chain[-1]
        base_data = self._read_chunk(base_info["pack"], base_info["offset"])

        # Decode delta steps backwards
        curr_data = base_data
        for info in reversed(chain[:-1]):
            delta = self._read_chunk(info["pack"], info["offset"])
            base_type, base_body = curr_data.split(b"\n", 1)
            target_body = DeltaEncoder.decode(base_body, delta)
            curr_data = base_type + b"\n" + target_body

        return curr_data

    def _read_chunk(self, pack_name: str, offset: int) -> bytes:
        pack_path = os.path.join(self.pack_dir, pack_name)
        with open(pack_path, "rb") as f:
            f.seek(offset)
            length = int.from_bytes(f.read(4), "big")
            compressed = f.read(length)
            return zlib.decompress(compressed)
