"""High-performance binary stream reader and writer with batch struct operations."""

import struct
from typing import Any


class ByteReader:
    """Bounded, high-performance binary reader backed by memoryview."""

    __slots__ = ("_offset", "_size", "_view")

    def __init__(self, data: bytes | bytearray | memoryview) -> None:
        self._view = memoryview(data)
        self._offset = 0
        self._size = len(self._view)

    @property
    def offset(self) -> int:
        return self._offset

    @property
    def remaining(self) -> int:
        return self._size - self._offset

    def seek(self, offset: int) -> None:
        if offset < 0 or offset > self._size:
            raise EOFError(f"Seek offset {offset} out of bounds [0, {self._size}]")
        self._offset = offset

    def skip(self, count: int) -> None:
        if self._offset + count > self._size or self._offset + count < 0:
            raise EOFError(
                f"Skip {count} bytes exceeds bounds (offset={self._offset}, size={self._size})"
            )
        self._offset += count

    def read_bytes(self, n: int) -> bytes:
        if n < 0 or self._offset + n > self._size:
            raise EOFError(
                f"Attempted to read {n} bytes at offset {self._offset}, available {self._size - self._offset}"
            )
        result = bytes(self._view[self._offset : self._offset + n])
        self._offset += n
        return result

    def read_slice(self, n: int) -> "ByteReader":
        if n < 0 or self._offset + n > self._size:
            raise EOFError(
                f"Attempted to slice {n} bytes at offset {self._offset}, available {self._size - self._offset}"
            )
        sub_view = self._view[self._offset : self._offset + n]
        self._offset += n
        return ByteReader(sub_view)

    def read_remaining(self) -> bytes:
        return self.read_bytes(self.remaining)

    def read_u8(self) -> int:
        if self._offset + 1 > self._size:
            raise EOFError(f"Unexpected EOF reading u8 at offset {self._offset}")
        val = self._view[self._offset]
        self._offset += 1
        return val

    def read_i8(self) -> int:
        return self.read_struct("<b")[0]

    def read_u16(self) -> int:
        return self.read_struct("<H")[0]

    def read_i16(self) -> int:
        return self.read_struct("<h")[0]

    def read_u32(self) -> int:
        return self.read_struct("<I")[0]

    def read_i32(self) -> int:
        return self.read_struct("<i")[0]

    def read_u64(self) -> int:
        return self.read_struct("<Q")[0]

    def read_i64(self) -> int:
        return self.read_struct("<q")[0]

    def read_f32(self) -> float:
        return self.read_struct("<f")[0]

    def read_f64(self) -> float:
        return self.read_struct("<d")[0]

    def read_fourcc(self) -> str:
        return self.read_bytes(4).decode("latin-1", errors="replace")

    def read_struct(self, fmt: str) -> tuple[Any, ...]:
        size = struct.calcsize(fmt)
        if self._offset + size > self._size:
            raise EOFError(
                f"Unexpected EOF reading struct '{fmt}' (size {size}) at offset {self._offset}, total {self._size}"
            )
        res = struct.unpack_from(fmt, self._view, self._offset)
        self._offset += size
        return res


class ByteWriter:
    """High-performance binary writer backed by mutable bytearray."""

    __slots__ = ("_buf",)

    def __init__(self) -> None:
        self._buf = bytearray()

    @property
    def length(self) -> int:
        return len(self._buf)

    def __len__(self) -> int:
        return len(self._buf)

    def get_bytes(self) -> bytes:
        return bytes(self._buf)

    def write_bytes(self, data: bytes | bytearray | memoryview) -> None:
        self._buf.extend(data)

    def write_u8(self, v: int) -> None:
        self._buf.append(v & 0xFF)

    def write_i8(self, v: int) -> None:
        self.write_struct("<b", v)

    def write_u16(self, v: int) -> None:
        self.write_struct("<H", v)

    def write_i16(self, v: int) -> None:
        self.write_struct("<h", v)

    def write_u32(self, v: int) -> None:
        self.write_struct("<I", v)

    def write_i32(self, v: int) -> None:
        self.write_struct("<i", v)

    def write_u64(self, v: int) -> None:
        self.write_struct("<Q", v)

    def write_i64(self, v: int) -> None:
        self.write_struct("<q", v)

    def write_f32(self, v: float) -> None:
        self.write_struct("<f", v)

    def write_f64(self, v: float) -> None:
        self.write_struct("<d", v)

    def write_struct(self, fmt: str, *args: Any) -> None:
        self._buf.extend(struct.pack(fmt, *args))

    def pad_to(self, alignment: int, pad_byte: int = 0x00) -> int:
        rem = len(self._buf) % alignment
        if rem != 0:
            pad_len = alignment - rem
            self._buf.extend(bytes([pad_byte] * pad_len))
            return pad_len
        return 0
