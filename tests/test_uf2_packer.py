"""Unit tests for pure-Python ELF32-to-UF2 converter in tools/xiao_cli.py."""

from pathlib import Path
import struct
import tempfile
import pytest

from tools.xiao_cli import (
    elf_to_uf2,
    UF2_MAGIC_START0,
    UF2_MAGIC_START1,
    UF2_MAGIC_END,
    UF2_FLAG_FAMILY_ID_PRESENT,
    NRF52840_UF2_FAMILY_ID,
)


def create_synthetic_elf32(segments: list[tuple[int, bytes]]) -> bytes:
    """Create a minimal valid 32-bit Little-Endian ARM ELF binary with PT_LOAD segments."""
    # 52-byte ELF header
    e_ident = b"\x7fELF\x01\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00"
    e_type = 2  # ET_EXEC
    e_machine = 40  # EM_ARM
    e_version = 1
    e_entry = segments[0][0] if segments else 0x00001000
    e_phoff = 52
    e_shoff = 0
    e_flags = 0x05000000
    e_ehsize = 52
    e_phentsize = 32
    e_phnum = len(segments)
    e_shentsize = 40
    e_shnum = 0
    e_shstrndx = 0

    header = (
        e_ident
        + struct.pack(
            "<HHIIIIIHHHHHH",
            e_type,
            e_machine,
            e_version,
            e_entry,
            e_phoff,
            e_shoff,
            e_flags,
            e_ehsize,
            e_phentsize,
            e_phnum,
            e_shentsize,
            e_shnum,
            e_shstrndx,
        )
    )

    offset = 52 + len(segments) * 32
    phdrs = bytearray()
    payloads = bytearray()

    for paddr, data in segments:
        p_type = 1  # PT_LOAD
        p_offset = offset + len(payloads)
        p_vaddr = paddr
        p_paddr = paddr
        p_filesz = len(data)
        p_memsz = len(data)
        p_flags = 5  # RX
        p_align = 4

        phdrs.extend(
            struct.pack(
                "<IIIIIIII",
                p_type,
                p_offset,
                p_vaddr,
                p_paddr,
                p_filesz,
                p_memsz,
                p_flags,
                p_align,
            )
        )
        payloads.extend(data)

    return header + phdrs + payloads


def test_elf_to_uf2_packing_and_magic():
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        elf_path = tmp_path / "test.elf"
        uf2_path = tmp_path / "test.uf2"

        # 512 bytes of synthetic firmware code starting at 0x00027000 (SoftDevice S140 7.3.0 app origin)
        test_payload = bytes([i % 256 for i in range(512)])
        elf_bytes = create_synthetic_elf32([(0x00027000, test_payload)])
        elf_path.write_bytes(elf_bytes)

        num_blocks, base_addr, payload_bytes = elf_to_uf2(elf_path, uf2_path)
        assert base_addr == 0x00027000
        assert uf2_path.exists()
        uf2_data = uf2_path.read_bytes()

        # Each UF2 block is exactly 512 bytes
        assert len(uf2_data) == num_blocks * 512
        assert num_blocks >= 2

        # Verify every block structure
        for b in range(num_blocks):
            block = uf2_data[b * 512 : (b + 1) * 512]
            (
                m0,
                m1,
                flags,
                target_addr,
                payload_size,
                block_no,
                total_blocks,
                family,
                chunk_and_pad,
                m_end,
            ) = struct.unpack("<IIIIIIII476sI", block)

            assert m0 == UF2_MAGIC_START0
            assert m1 == UF2_MAGIC_START1
            assert flags == UF2_FLAG_FAMILY_ID_PRESENT
            assert target_addr == 0x00027000 + b * 256
            assert payload_size == 256
            assert block_no == b
            assert total_blocks == num_blocks
            assert family == NRF52840_UF2_FAMILY_ID
            assert m_end == UF2_MAGIC_END
