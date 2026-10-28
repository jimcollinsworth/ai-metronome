//! Pure-Rust Bluetooth Low Energy (BLE) Advertiser PDU Builder (`no_std`)
//!
//! Constructs BLE 4.0+ Non-Connectable Undirected Advertising (`ADV_NONCONN_IND`)
//! packets for direct transmission via the Nordic `NRF_RADIO` peripheral on
//! primary advertising channels 37 (2402 MHz), 38 (2426 MHz), and 39 (2480 MHz).
//!
//! Encodes the current metronome tempo (BPM) using the **BTHome v2** open
//! broadcast standard (16-bit Service Data UUID `0xFCD2`), which is natively
//! decoded and logged by the Android **Sensor Logger** app (`tszheichoi/sensor-ble`)
//! as well as Home Assistant and nRF Connect.

/// Maximum total length of a legacy BLE advertising PDU in RAM:
/// 2-byte header (`S0` + `Length`) + 6-byte `AdvA` MAC + 31-byte `AdvData` = 39 bytes.
pub const MAX_BLE_PDU_LEN: usize = 39;

/// BLE PDU header byte `S0`:
/// - Bits `0..=3`: PDU Type `0b0010` (`ADV_NONCONN_IND`, non-connectable undirected advertising)
/// - Bit `6` (`TxAdd`): `1` (Random Static Advertiser Address)
pub const PDU_HEADER_ADV_NONCONN_RANDOM: u8 = 0x42;

/// Primary BLE advertising channels and their `NRF_RADIO.FREQUENCY` offsets (in MHz above 2400 MHz).
/// - Channel 37: 2402 MHz (`FREQUENCY = 2`)
/// - Channel 38: 2426 MHz (`FREQUENCY = 26`)
/// - Channel 39: 2480 MHz (`FREQUENCY = 80`)
pub const BLE_ADV_CHANNELS: [(u8, u8); 3] = [(37, 2), (38, 26), (39, 80)];

/// BTHome v2 16-bit Service UUID (`0xFCD2` in little-endian: `[0xD2, 0xFC]`).
pub const BTHOME_V2_UUID_LE: [u8; 2] = [0xD2, 0xFC];

/// BTHome v2 Device Information byte (`0x40` = version 2, unencrypted, regular trigger).
pub const BTHOME_V2_INFO_UNENCRYPTED: u8 = 0x40;

/// BTHome v2 Object ID `0x02`: Temperature / high-precision signed 16-bit value (`factor = 0.01`).
/// Used so Android Sensor Logger plots fractional BPM (e.g., `120.50` for 120.5 BPM).
pub const BTHOME_OBJ_TEMP_0_01: u8 = 0x02;

/// BTHome v2 Object ID `0x0A`: Energy / unsigned 24-bit value (`factor = 0.001`), or
/// Object ID `0x3D`: unsigned 16-bit count (`factor = 1`).
/// We include `0x3D` (uint16 count) for integer BPM and `0x2E` (uint8 humidity/percent) or `0x02`
/// so all BTHome v2 decoders display the tempo immediately.
pub const BTHOME_OBJ_COUNT_U16: u8 = 0x3D;

/// Convert raw `FICR.DEVICEADDR[0]` and `FICR.DEVICEADDR[1]` registers into a valid
/// 6-byte BLE Random Static Address (little-endian byte order, with the two most
/// significant bits of byte 5 set to `11` per Bluetooth Core Spec Vol 6, Part B, 1.3.2.1).
pub fn format_random_static_mac(deviceaddr0: u32, deviceaddr1: u32) -> [u8; 6] {
    let b0 = (deviceaddr0 & 0xFF) as u8;
    let b1 = ((deviceaddr0 >> 8) & 0xFF) as u8;
    let b2 = ((deviceaddr0 >> 16) & 0xFF) as u8;
    let b3 = ((deviceaddr0 >> 24) & 0xFF) as u8;
    let b4 = (deviceaddr1 & 0xFF) as u8;
    // Top two bits of the most significant address byte MUST be 11 (0xC0) for Random Static Address
    let b5 = (((deviceaddr1 >> 8) & 0xFF) as u8) | 0xC0;
    [b0, b1, b2, b3, b4, b5]
}

/// Build a complete, EasyDMA-ready BLE Advertising PDU containing the current tempo in BPM.
///
/// ### Packet Layout in `pdu_buf`:
/// - `pdu_buf[0]`: `S0` Header (`0x42` = `ADV_NONCONN_IND` + Random Address `TxAdd=1`)
/// - `pdu_buf[1]`: Payload length (`6` MAC bytes + `AdvData` bytes)
/// - `pdu_buf[2..8]`: 6-byte Advertiser Address (`AdvA`, little-endian)
/// - `pdu_buf[8..8+adv_len]`: Advertising Data (`AdvData`) structures:
///   1. **Flags** (`0x01`): `[0x02, 0x01, 0x06]` (`LE General Discoverable Mode | BR/EDR Not Supported`)
///   2. **Complete Local Name** (`0x09`): `"AI-METRO"` (`[0x09, 0x09, b'A', b'I', b'-', b'M', b'E', b'T', b'R', b'O']`)
///   3. **Service Data - 16-bit UUID** (`0x16`): BTHome v2 (`UUID = 0xFCD2`, `Info = 0x40`)
///      followed by sorted BTHome Object IDs:
///      - Object `0x02` (`int16` little-endian, factor `0.01`): `round(bpm * 100.0)`
///        (e.g., `120.5 BPM` -> `12050` -> `120.50` in Sensor Logger)
///      - Object `0x3D` (`uint16` little-endian, factor `1`): `round(bpm)`
///        (e.g., `120.5 BPM` -> `121` count in Sensor Logger)
///
/// Returns `(pdu_buf, total_bytes)`.
pub fn build_tempo_adv_pdu(mac: [u8; 6], bpm: f32) -> ([u8; MAX_BLE_PDU_LEN], usize) {
    let clamped_bpm = if bpm.is_nan() || bpm < 0.0 {
        0.0
    } else if bpm > 320.0 {
        320.0
    } else {
        bpm
    };

    // Scale to hundredths of BPM (factor 0.01) with half-up rounding
    let bpm_x100 = (clamped_bpm * 100.0 + 0.5) as u16 as i16;
    let bpm_x100_le = bpm_x100.to_le_bytes();

    // Integer rounded BPM for Object 0x3D (uint16 count)
    let bpm_int = (clamped_bpm + 0.5) as u16;
    let bpm_int_le = bpm_int.to_le_bytes();

    let mut pdu = [0u8; MAX_BLE_PDU_LEN];

    // 1. BLE Link Layer Header (S0 + Length placeholder)
    pdu[0] = PDU_HEADER_ADV_NONCONN_RANDOM;

    // 2. 6-byte Advertiser MAC Address (ensure Random Static bits are set on MSB)
    pdu[2] = mac[0];
    pdu[3] = mac[1];
    pdu[4] = mac[2];
    pdu[5] = mac[3];
    pdu[6] = mac[4];
    pdu[7] = mac[5] | 0xC0;

    // 3. Advertising Data (AdvData) starting at index 8
    let mut idx = 8;

    // AD Structure 1: Flags (3 bytes)
    pdu[idx] = 0x02; // Length: 2 bytes (Type + 1 value byte)
    pdu[idx + 1] = 0x01; // AD Type: Flags
    pdu[idx + 2] = 0x06; // LE General Discoverable (0x02) | BR/EDR Not Supported (0x04)
    idx += 3;

    // AD Structure 2: Complete Local Name "AI-METRO" (10 bytes)
    let name = b"AI-METRO";
    pdu[idx] = (1 + name.len()) as u8; // Length: 9
    pdu[idx + 1] = 0x09; // AD Type: Complete Local Name
    pdu[idx + 2..idx + 2 + name.len()].copy_from_slice(name);
    idx += 2 + name.len();

    // AD Structure 3: BTHome v2 16-bit Service Data (11 bytes)
    // Payload: Type (0x16) + UUID (0xD2, 0xFC) + Info (0x40) + [0x02, lo, hi] + [0x3D, lo, hi]
    pdu[idx] = 10; // Length: 1 (AD Type) + 2 (UUID) + 1 (Info) + 3 (Obj 0x02) + 3 (Obj 0x3D) = 10
    pdu[idx + 1] = 0x16; // AD Type: Service Data - 16-bit UUID
    pdu[idx + 2] = BTHOME_V2_UUID_LE[0]; // 0xD2
    pdu[idx + 3] = BTHOME_V2_UUID_LE[1]; // 0xFC
    pdu[idx + 4] = BTHOME_V2_INFO_UNENCRYPTED; // 0x40 (BTHome v2, unencrypted)
    // Object 0x02: signed 16-bit integer, factor 0.01 (BPM with 0.01 resolution)
    pdu[idx + 5] = BTHOME_OBJ_TEMP_0_01;
    pdu[idx + 6] = bpm_x100_le[0];
    pdu[idx + 7] = bpm_x100_le[1];
    // Object 0x3D: unsigned 16-bit count, factor 1 (integer BPM)
    pdu[idx + 8] = BTHOME_OBJ_COUNT_U16;
    pdu[idx + 9] = bpm_int_le[0];
    pdu[idx + 10] = bpm_int_le[1];
    idx += 11;

    // Total payload length after the 2-byte (S0 + Length) header
    pdu[1] = (idx - 2) as u8;

    (pdu, idx)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_format_random_static_mac_sets_top_two_bits() {
        let mac = format_random_static_mac(0x11223344, 0x00005566);
        assert_eq!(mac[0], 0x44);
        assert_eq!(mac[1], 0x33);
        assert_eq!(mac[2], 0x22);
        assert_eq!(mac[3], 0x11);
        assert_eq!(mac[4], 0x66);
        // 0x55 | 0xC0 == 0xD5 (top two bits set to 11 for Random Static Address)
        assert_eq!(mac[5], 0xD5);
        assert_eq!(mac[5] & 0xC0, 0xC0);
    }

    #[test]
    fn test_build_tempo_adv_pdu_structure_and_bthome_120_5_bpm() {
        let mac = [0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF];
        let (pdu, total_len) = build_tempo_adv_pdu(mac, 120.5);

        // Total length: 2 (header) + 6 (MAC) + 3 (Flags) + 10 (Name) + 11 (BTHome) = 32 bytes
        assert_eq!(total_len, 32);
        assert!(total_len <= MAX_BLE_PDU_LEN);

        // S0 = 0x42 (ADV_NONCONN_IND | TxAdd=1)
        assert_eq!(pdu[0], 0x42);
        // Length = 30 bytes (6 MAC + 24 AdvData)
        assert_eq!(pdu[1], 30);

        // MAC address in bytes 2..8
        assert_eq!(&pdu[2..8], &[0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF]);

        // AD 1: Flags [0x02, 0x01, 0x06]
        assert_eq!(&pdu[8..11], &[0x02, 0x01, 0x06]);

        // AD 2: Complete Local Name "AI-METRO"
        assert_eq!(pdu[11], 0x09);
        assert_eq!(pdu[12], 0x09);
        assert_eq!(&pdu[13..21], b"AI-METRO");

        // AD 3: BTHome v2 Service Data (UUID 0xFCD2)
        assert_eq!(pdu[21], 10); // AD length
        assert_eq!(pdu[22], 0x16); // Service Data 16-bit UUID
        assert_eq!(pdu[23], 0xD2); // UUID LSB
        assert_eq!(pdu[24], 0xFC); // UUID MSB
        assert_eq!(pdu[25], 0x40); // BTHome v2 unencrypted header

        // Object 0x02: 120.50 BPM -> 12050 (0x2F12 -> LE [0x12, 0x2F])
        assert_eq!(pdu[26], 0x02);
        let decoded_x100 = i16::from_le_bytes([pdu[27], pdu[28]]);
        assert_eq!(decoded_x100, 12050);

        // Object 0x3D: rounded integer 121 BPM (0x0079 -> LE [0x79, 0x00])
        assert_eq!(pdu[29], 0x3D);
        let decoded_int = u16::from_le_bytes([pdu[30], pdu[31]]);
        assert_eq!(decoded_int, 121);
    }

    #[test]
    fn test_build_tempo_adv_pdu_zero_and_clamping() {
        let mac = [0x01, 0x02, 0x03, 0x04, 0x05, 0x06];

        // Negative / zero BPM clamps cleanly to 0
        let (pdu_zero, _) = build_tempo_adv_pdu(mac, -15.0);
        assert_eq!(i16::from_le_bytes([pdu_zero[27], pdu_zero[28]]), 0);
        assert_eq!(u16::from_le_bytes([pdu_zero[30], pdu_zero[31]]), 0);
        // Also verify MSB of MAC had 0xC0 applied
        assert_eq!(pdu_zero[7] & 0xC0, 0xC0);

        // Out-of-range high BPM clamps cleanly to 320.0 BPM (32000)
        let (pdu_high, _) = build_tempo_adv_pdu(mac, 999.0);
        assert_eq!(i16::from_le_bytes([pdu_high[27], pdu_high[28]]), 32000);
        assert_eq!(u16::from_le_bytes([pdu_high[30], pdu_high[31]]), 320);
    }
}
