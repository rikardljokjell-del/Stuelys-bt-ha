"""SG application messages carried by the authenticated CSRmesh bearer."""

from recsrmesh.mcp_crypto import decrypt_packet, generate_key

FEF1 = "0000fef1-0000-1000-8000-00805f9b34fb"
APP = 0x8000


def network_key(password: str) -> bytes:
    return generate_key(password.encode("utf-8") + b"\x00MCP")


def _switch_message(key, frame, switch, length, opcode):
    if len(frame) != length or int.from_bytes(frame[3:5], "little") != switch:
        return None
    packet = decrypt_packet(key, frame)
    if packet is None:
        return None
    data = packet["decpayload"]
    group = int.from_bytes(data[:2], "little")
    if not 0 < group < APP or data[2:4] != opcode:
        return None
    return group, data, packet["seq"]


def switch_power(key: bytes, frame: bytes, switch: int):
    """Recognize the short FF03 observed on a physical switch press."""
    decoded = _switch_message(key, frame, switch, 23, b"\xff\x03")
    if decoded is None:
        return None
    group, data, seq = decoded
    if data[6] not in (0, 1) or data[7] != 0:
        return None
    return group, data[4:6], bool(data[6]), seq


def switch_dimming(key: bytes, frame: bytes, switch: int):
    """Recognize a physical dim-up, dim-down or stop message."""
    decoded = _switch_message(key, frame, switch, 21, b"\xff\x23")
    if decoded is None:
        return None
    group, data, seq = decoded
    if data[6] not in (1, 2, 3):
        return None
    return group, data[4:6], data[6], seq


def power_command(location: bytes, on: bool, tid: int, *, percent: int = 0) -> bytes:
    """Short group command from the AV/PÅ captures (one-byte transaction ID)."""
    return b"\xff\x03" + location + bytes([on, percent, tid & 0xFF])


def dim_command(location: bytes, action: int) -> bytes:
    """Group FF23 from the wall-switch captures. 1 up, 2 down, 3 stop."""
    return b"\xff\x23" + location + bytes([action])


def level_command(location: bytes, on: bool, percent: int, tid: int) -> bytes:
    """SG's direct device command (two-byte transaction ID, white channel zero)."""
    return b"\xff\x03" + location + bytes([on, percent]) + tid.to_bytes(2, "little") + b"\x00"


def device_name(source: int, data: bytes, location: bytes, name: str):
    if source in (0, APP, 0x8001, 0xFFFF):
        return None
    if (len(data) >= 13 and data[2:6] == b"\xff\x11" + location
            and data[6:12] == name[1:].encode("ascii")):
        return source
    return None


def device_status(source: int, data: bytes, node: int, location: bytes):
    """Return percent, including zero for off, only for the addressed node."""
    if source != node or len(data) < 8 or data[2:6] != b"\xff\x05" + location:
        return None
    power, percent = data[6:8]
    if power == 0:
        return 0
    if power == 1 and 1 <= percent <= 100:
        return percent
    return None
