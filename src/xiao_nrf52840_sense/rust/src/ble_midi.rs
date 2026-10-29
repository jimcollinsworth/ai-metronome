//! Pure-Rust Bluetooth Low Energy MIDI (BLE-MIDI) Link-Layer, ATT/GATT Server & Packet Engine (`no_std`)
//!
//! Implements the Apple / MMA Bluetooth Low Energy MIDI Specification:
//! - **BLE MIDI Service UUID**: `03B80E5A-EDE8-4B33-A751-6CE34EC4C700`
//! - **BLE MIDI I/O Characteristic UUID**: `7772E5DB-3868-4112-A1A9-F2669D106BF3`
//!
//! Designed for both **CME WIDI Jack** (auto-pairing BLE MIDI Central) and **iPadOS / macOS /
//! Windows / Web Bluetooth** (Pianoteq, CoreMIDI, Chrome Web Bluetooth).

/// Maximum BLE Link-Layer Data Channel PDU payload size (supports DLE up to 251 bytes).
pub const MAX_DATA_PDU_PAYLOAD: usize = 64;

/// Maximum total BLE PDU buffer size (2-byte header + payload).
pub const MAX_DATA_PDU_BUF: usize = MAX_DATA_PDU_PAYLOAD + 2;

/// BLE Advertising PDU header `S0` for `ADV_IND` (Connectable & Scannable Undirected, CSA #1, Random Static `TxAdd=1`).
pub const PDU_HEADER_ADV_IND_RANDOM: u8 = 0x40;

/// BLE Advertising PDU header `S0` for `SCAN_RSP` (Scan Response, Random Static `TxAdd=1`).
pub const PDU_HEADER_SCAN_RSP_RANDOM: u8 = 0x44;

/// Advertising channel PDU types (lower 4 bits of `S0`).
pub const ADV_PDU_TYPE_SCAN_REQ: u8 = 0x03;
pub const ADV_PDU_TYPE_CONNECT_IND: u8 = 0x05;

/// Data channel Link-Layer IDs (`LLID`, bits `0..=1` of Data PDU `S0`).
pub const LLID_CONTINUED_OR_EMPTY: u8 = 0x01;
pub const LLID_START_L2CAP: u8 = 0x02;
pub const LLID_CONTROL: u8 = 0x03;

/// Link-Layer Control PDU Opcodes (`LLID = 0b11`).
pub const LL_CONNECTION_UPDATE_IND: u8 = 0x00;
pub const LL_CHANNEL_MAP_IND: u8 = 0x01;
pub const LL_TERMINATE_IND: u8 = 0x02;
pub const LL_ENC_REQ: u8 = 0x03;
pub const LL_UNKNOWN_RSP: u8 = 0x07;
pub const LL_FEATURE_REQ: u8 = 0x08;
pub const LL_FEATURE_RSP: u8 = 0x09;
pub const LL_VERSION_IND: u8 = 0x0C;
pub const LL_REJECT_IND: u8 = 0x0D;
pub const LL_SLAVE_FEATURE_REQ: u8 = 0x0E;
pub const LL_PING_REQ: u8 = 0x12;
pub const LL_PING_RSP: u8 = 0x13;
pub const LL_LENGTH_REQ: u8 = 0x14;
pub const LL_LENGTH_RSP: u8 = 0x15;

/// L2CAP Channel Identifiers.
pub const L2CAP_CID_ATT: u16 = 0x0004;
pub const L2CAP_CID_SIGNALING: u16 = 0x0005;
pub const L2CAP_CID_SMP: u16 = 0x0006;

/// ATT Protocol Opcodes (`CID = 0x0004`).
pub const ATT_ERROR_RSP: u8 = 0x01;
pub const ATT_EXCHANGE_MTU_REQ: u8 = 0x02;
pub const ATT_EXCHANGE_MTU_RSP: u8 = 0x03;
pub const ATT_FIND_INFO_REQ: u8 = 0x04;
pub const ATT_FIND_INFO_RSP: u8 = 0x05;
pub const ATT_FIND_BY_TYPE_VALUE_REQ: u8 = 0x06;
pub const ATT_FIND_BY_TYPE_VALUE_RSP: u8 = 0x07;
pub const ATT_READ_BY_TYPE_REQ: u8 = 0x08;
pub const ATT_READ_BY_TYPE_RSP: u8 = 0x09;
pub const ATT_READ_REQ: u8 = 0x0A;
pub const ATT_READ_RSP: u8 = 0x0B;
pub const ATT_READ_BLOB_REQ: u8 = 0x0C;
pub const ATT_READ_BLOB_RSP: u8 = 0x0D;
pub const ATT_READ_BY_GROUP_TYPE_REQ: u8 = 0x10;
pub const ATT_READ_BY_GROUP_TYPE_RSP: u8 = 0x11;
pub const ATT_WRITE_REQ: u8 = 0x12;
pub const ATT_WRITE_RSP: u8 = 0x13;
pub const ATT_HANDLE_VALUE_NTF: u8 = 0x1B;
pub const ATT_WRITE_CMD: u8 = 0x52;

/// ATT Error Codes.
pub const ATT_ERR_INVALID_HANDLE: u8 = 0x01;
pub const ATT_ERR_READ_NOT_PERMITTED: u8 = 0x02;
pub const ATT_ERR_REQ_NOT_SUPPORTED: u8 = 0x06;
pub const ATT_ERR_ATTR_NOT_FOUND: u8 = 0x0A;

/// Apple / MMA BLE MIDI Service UUID (`03B80E5A-EDE8-4B33-A751-6CE34EC4C700`) in little-endian byte order.
pub const BLE_MIDI_SERVICE_UUID_LE: [u8; 16] = [
    0x00, 0xC7, 0xC4, 0x4E, 0xE3, 0x6C, 0x51, 0xA7, 0x33, 0x4B, 0xE8, 0xED, 0x5A, 0x0E, 0xB8, 0x03,
];

/// Apple / MMA BLE MIDI I/O Characteristic UUID (`7772E5DB-3868-4112-A1A9-F2669D106BF3`) in little-endian byte order.
pub const BLE_MIDI_CHAR_UUID_LE: [u8; 16] = [
    0xF3, 0x6B, 0x10, 0x9D, 0x66, 0xF2, 0xA9, 0xA1, 0x12, 0x41, 0x68, 0x38, 0xDB, 0xE5, 0x72, 0x77,
];

/// GATT Attribute Handles for our BLE MIDI Server.
pub const HANDLE_GAP_SERVICE: u16 = 0x0001;
pub const HANDLE_GAP_NAME_DECL: u16 = 0x0002;
pub const HANDLE_GAP_NAME_VAL: u16 = 0x0003;
pub const HANDLE_GAP_APPEARANCE_DECL: u16 = 0x0004;
pub const HANDLE_GAP_APPEARANCE_VAL: u16 = 0x0005;
pub const HANDLE_GAP_PPCP_DECL: u16 = 0x0006;
pub const HANDLE_GAP_PPCP_VAL: u16 = 0x0007;

pub const HANDLE_GATT_SERVICE: u16 = 0x0008;
pub const HANDLE_GATT_SVC_CHANGED_DECL: u16 = 0x0009;
pub const HANDLE_GATT_SVC_CHANGED_VAL: u16 = 0x000A;
pub const HANDLE_GATT_SVC_CHANGED_CCCD: u16 = 0x000B;

pub const HANDLE_MIDI_SERVICE: u16 = 0x000C;
pub const HANDLE_MIDI_IO_DECL: u16 = 0x000D;
pub const HANDLE_MIDI_IO_VAL: u16 = 0x000E;
pub const HANDLE_MIDI_IO_CCCD: u16 = 0x000F;

/// Standard MIDI 1.0 Real-Time System Messages.
pub const MIDI_RT_TIMING_CLOCK: u8 = 0xF8;
pub const MIDI_RT_START: u8 = 0xFA;
pub const MIDI_RT_CONTINUE: u8 = 0xFB;
pub const MIDI_RT_STOP: u8 = 0xFC;

/// Configurable parameters for the BLE MIDI Fixed-Beat Test App.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct BtMidiConfig {
    /// Whether the beat generator is currently playing.
    pub running: bool,
    /// Tempo in Beats Per Minute (`30.0..=240.0`).
    pub bpm: f32,
    /// Beats per bar (`1..=8`, e.g. `4` for 4/4, `3` for 3/4).
    pub meter: u8,
    /// MIDI Channel (`1..=16`, where `1` = Pianoteq/Synth Ch 1, `10` = GM Percussion).
    pub midi_channel: u8,
    /// MIDI Note number (`0..=127`) for Beat 1 (Downbeat / Accent). Default: `76` (High Woodblock).
    pub accent_note: u8,
    /// MIDI Velocity (`1..=127`) for Beat 1. Default: `120`.
    pub accent_velocity: u8,
    /// MIDI Note number (`0..=127`) for weak beats (Beats 2..N). Default: `77` (Low Woodblock).
    pub beat_note: u8,
    /// MIDI Velocity (`1..=127`) for weak beats. Default: `80`.
    pub beat_velocity: u8,
    /// Note-On gate duration in milliseconds before Note-Off (`5..=250 ms`). Default: `25`.
    pub note_gate_ms: u16,
    /// Whether to transmit Note-On / Note-Off messages on each beat.
    pub send_notes: bool,
    /// Whether to transmit 24 PPQN Real-Time MIDI Timing Clock (`0xF8`) pulses.
    pub send_clock: bool,
}

impl Default for BtMidiConfig {
    fn default() -> Self {
        Self::new()
    }
}

impl BtMidiConfig {
    pub const fn new() -> Self {
        Self {
            running: true,
            bpm: 120.0,
            meter: 4,
            midi_channel: 10,
            accent_note: 76,      // GM High Wood Block (E5)
            accent_velocity: 120, // Strong downbeat
            beat_note: 77,        // GM Low Wood Block (F5)
            beat_velocity: 80,    // Standard quarter-note beat
            note_gate_ms: 25,     // Crisp 25 ms click gate
            send_notes: true,
            send_clock: true,
        }
    }

    /// Apply a configuration parameter sent via Web Bluetooth SysEx (`F0 7D 4D 45 <param> <hi> <lo> F7`).
    pub fn apply_sysex_param(&mut self, param_id: u8, value: u16) -> bool {
        match param_id {
            0x01 => {
                self.running = value != 0;
                true
            }
            0x02 => {
                // Value is BPM * 10 (e.g. 1205 = 120.5 BPM) or integer BPM if <= 240
                let new_bpm = if value > 300 {
                    (value as f32) * 0.1
                } else {
                    value as f32
                };
                self.bpm = new_bpm.clamp(30.0, 240.0);
                true
            }
            0x03 => {
                self.meter = (value as u8).clamp(1, 8);
                true
            }
            0x04 => {
                self.midi_channel = (value as u8).clamp(1, 16);
                true
            }
            0x05 => {
                self.accent_note = (value as u8) & 0x7F;
                true
            }
            0x06 => {
                self.accent_velocity = (value as u8).clamp(1, 127);
                true
            }
            0x07 => {
                self.beat_note = (value as u8) & 0x7F;
                true
            }
            0x08 => {
                self.beat_velocity = (value as u8).clamp(1, 127);
                true
            }
            0x09 => {
                self.note_gate_ms = value.clamp(5, 250);
                true
            }
            0x0A => {
                self.send_notes = value != 0;
                true
            }
            0x0B => {
                self.send_clock = value != 0;
                true
            }
            _ => false,
        }
    }
}

/// Build a connectable `ADV_IND` PDU advertising the 128-bit BLE MIDI Service UUID (`03B80E5A-...`)
/// and local name `"AI-METRO"` within the 31-byte legacy `AdvData` budget.
///
/// ### Layout (`39` bytes total):
/// - `pdu[0]`: `0x40` (`ADV_IND`, CSA #1, Random Static `TxAdd=1`)
/// - `pdu[1]`: `37` (`6` MAC + `31` AdvData)
/// - `pdu[2..8]`: 6-byte Advertiser MAC (`mac[5] | 0xC0`)
/// - `pdu[8..11]`: Flags (`[0x02, 0x01, 0x06]`) — 3 bytes
/// - `pdu[11..29]`: Complete 128-bit Service UUID (`03B80E5A-...`) — 18 bytes
/// - `pdu[29..39]`: Complete Local Name `"AI-METRO"` — 10 bytes
pub fn build_midi_adv_ind_pdu(mac: [u8; 6]) -> ([u8; 39], usize) {
    let mut pdu = [0u8; 39];
    pdu[0] = PDU_HEADER_ADV_IND_RANDOM;
    pdu[1] = 37; // 6 MAC + 31 AdvData

    pdu[2] = mac[0];
    pdu[3] = mac[1];
    pdu[4] = mac[2];
    pdu[5] = mac[3];
    pdu[6] = mac[4];
    pdu[7] = mac[5] | 0xC0;

    let mut idx = 8;

    // 1. Flags (3 bytes)
    pdu[idx] = 0x02;
    pdu[idx + 1] = 0x01;
    pdu[idx + 2] = 0x06;
    idx += 3;

    // 2. Complete List of 128-bit Service UUIDs: BLE MIDI (18 bytes)
    pdu[idx] = 17;
    pdu[idx + 1] = 0x07;
    pdu[idx + 2..idx + 18].copy_from_slice(&BLE_MIDI_SERVICE_UUID_LE);
    idx += 18;

    // 3. Complete Local Name: "AI-METRO" (10 bytes)
    let name = b"AI-METRO";
    pdu[idx] = (1 + name.len()) as u8;
    pdu[idx + 1] = 0x09;
    pdu[idx + 2..idx + 2 + name.len()].copy_from_slice(name);
    idx += 2 + name.len();

    (pdu, idx)
}

/// Build a `SCAN_RSP` PDU with the Complete Local Name `"AI-METRO"`, Tx Power (`+4 dBm`),
/// and Apple BLE-MIDI Preferred Slave Connection Interval (`7.5 ms - 15.0 ms`).
pub fn build_midi_scan_rsp_pdu(mac: [u8; 6]) -> ([u8; 39], usize) {
    let mut pdu = [0u8; 39];
    pdu[0] = PDU_HEADER_SCAN_RSP_RANDOM;

    pdu[2] = mac[0];
    pdu[3] = mac[1];
    pdu[4] = mac[2];
    pdu[5] = mac[3];
    pdu[6] = mac[4];
    pdu[7] = mac[5] | 0xC0;

    let mut idx = 8;

    // 1. Complete Local Name: "AI-METRO" (10 bytes)
    let name = b"AI-METRO";
    pdu[idx] = (1 + name.len()) as u8;
    pdu[idx + 1] = 0x09;
    pdu[idx + 2..idx + 2 + name.len()].copy_from_slice(name);
    idx += 2 + name.len();

    // 2. Slave Connection Interval Range: 7.5 ms (0x0006) to 15.0 ms (0x000C) (6 bytes)
    pdu[idx] = 0x05;
    pdu[idx + 1] = 0x12;
    pdu[idx + 2] = 0x06;
    pdu[idx + 3] = 0x00;
    pdu[idx + 4] = 0x0C;
    pdu[idx + 5] = 0x00;
    idx += 6;

    // 3. Tx Power Level: +4 dBm (3 bytes)
    pdu[idx] = 0x02;
    pdu[idx + 1] = 0x0A;
    pdu[idx + 2] = 0x04;
    idx += 3;

    pdu[1] = (idx - 2) as u8;
    (pdu, idx)
}

/// Parsed connection parameters extracted from a Central's `CONNECT_IND` PDU.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ConnectIndParams {
    pub peer_mac: [u8; 6],
    pub access_address: u32,
    pub crc_init: u32,
    pub win_size: u8,
    pub win_offset: u16,
    pub interval: u16,
    pub latency: u16,
    pub timeout: u16,
    pub ch_map: [u8; 5],
    pub hop: u8,
    pub sca: u8,
}

/// Check if an incoming Advertising Channel PDU is a `SCAN_REQ` (`0x03`) addressed to `our_mac`.
pub fn is_scan_req_for_us(rx_pdu: &[u8], our_mac: &[u8; 6]) -> bool {
    if rx_pdu.len() < 14 {
        return false;
    }
    let pdu_type = rx_pdu[0] & 0x0F;
    let len = (rx_pdu[1] & 0x3F) as usize;
    if pdu_type != ADV_PDU_TYPE_SCAN_REQ || len != 12 {
        return false;
    }
    rx_pdu[8..14] == our_mac[..]
}

/// Parse an incoming `CONNECT_IND` (`0x05`) PDU if it is addressed to `our_mac`.
pub fn parse_connect_ind(rx_pdu: &[u8], our_mac: &[u8; 6]) -> Option<ConnectIndParams> {
    if rx_pdu.len() < 36 {
        return None;
    }
    let pdu_type = rx_pdu[0] & 0x0F;
    let len = (rx_pdu[1] & 0x3F) as usize;
    if pdu_type != ADV_PDU_TYPE_CONNECT_IND || len != 34 {
        return None;
    }
    // Bytes 8..14 hold AdvA (the target peripheral's MAC address)
    if rx_pdu[8..14] != our_mac[..] {
        return None;
    }

    let mut peer_mac = [0u8; 6];
    peer_mac.copy_from_slice(&rx_pdu[2..8]);

    let access_address = u32::from_le_bytes([rx_pdu[14], rx_pdu[15], rx_pdu[16], rx_pdu[17]]);
    let crc_init =
        (rx_pdu[18] as u32) | ((rx_pdu[19] as u32) << 8) | ((rx_pdu[20] as u32) << 16);
    let win_size = rx_pdu[21];
    let win_offset = u16::from_le_bytes([rx_pdu[22], rx_pdu[23]]);
    let interval = u16::from_le_bytes([rx_pdu[24], rx_pdu[25]]);
    let latency = u16::from_le_bytes([rx_pdu[26], rx_pdu[27]]);
    let timeout = u16::from_le_bytes([rx_pdu[28], rx_pdu[29]]);

    let ch_map = [
        rx_pdu[30],
        rx_pdu[31],
        rx_pdu[32],
        rx_pdu[33],
        rx_pdu[34] & 0x1F,
    ];
    let hop = rx_pdu[35] & 0x1F;
    let sca = (rx_pdu[35] >> 5) & 0x07;

    if interval < 6 || hop < 5 || hop > 16 {
        return None;
    }

    Some(ConnectIndParams {
        peer_mac,
        access_address,
        crc_init,
        win_size,
        win_offset,
        interval,
        latency,
        timeout,
        ch_map,
        hop,
        sca,
    })
}

/// BLE Channel Selection Algorithm #1 (CSA #1) State Machine.
#[derive(Clone, Copy, Debug)]
pub struct ChannelHopper {
    pub last_unmapped: u8,
    pub hop: u8,
    pub ch_map: [u8; 5],
    pub used_channels: [u8; 37],
    pub num_used: u8,
}

impl ChannelHopper {
    pub fn new(ch_map: [u8; 5], hop: u8) -> Self {
        let mut hopper = Self {
            last_unmapped: 0,
            hop,
            ch_map: [0; 5],
            used_channels: [0; 37],
            num_used: 0,
        };
        hopper.update_channel_map(ch_map);
        hopper
    }

    /// Rebuild the remapping table when `CONNECT_IND` or `LL_CHANNEL_MAP_IND` updates the map.
    pub fn update_channel_map(&mut self, ch_map: [u8; 5]) {
        self.ch_map = ch_map;
        let mut count = 0usize;
        for ch in 0..37u8 {
            let byte_idx = (ch / 8) as usize;
            let bit_idx = ch % 8;
            if (self.ch_map[byte_idx] & (1 << bit_idx)) != 0 {
                self.used_channels[count] = ch;
                count += 1;
            }
        }
        if count == 0 {
            // Fallback safety: enable all 37 channels if an invalid zero map was sent
            for ch in 0..37u8 {
                self.used_channels[ch as usize] = ch;
            }
            self.num_used = 37;
        } else {
            self.num_used = count as u8;
        }
    }

    /// Compute the data channel index (`0..=36`) for the next BLE connection event.
    pub fn next_channel(&mut self) -> u8 {
        let unmapped = (self.last_unmapped + self.hop) % 37;
        self.last_unmapped = unmapped;
        let byte_idx = (unmapped / 8) as usize;
        let bit_idx = unmapped % 8;
        if (self.ch_map[byte_idx] & (1 << bit_idx)) != 0 {
            unmapped
        } else {
            let remap_idx = (unmapped % self.num_used) as usize;
            self.used_channels[remap_idx]
        }
    }
}

/// Convert a BLE Data Channel index (`0..=36`) into `NRF_RADIO.FREQUENCY` offset in MHz above 2400 MHz.
/// - Channels `0..=10` -> `2404..=2424 MHz` (`4 + 2 * ch`)
/// - Channels `11..=36` -> `2428..=2478 MHz` (`6 + 2 * ch`)
#[inline]
pub const fn data_channel_to_freq_mhz(ch: u8) -> u8 {
    if ch <= 10 {
        4 + ch * 2
    } else {
        6 + ch * 2
    }
}

/// Encode a 5-byte Apple BLE-MIDI Note-On packet (`[header, timestamp, 0x9n, note, velocity]`).
#[inline]
pub const fn encode_ble_midi_note_on(
    timestamp_ms: u16,
    channel: u8,
    note: u8,
    velocity: u8,
) -> [u8; 5] {
    let ts13 = timestamp_ms & 0x1FFF;
    let header = 0x80 | ((ts13 >> 7) as u8 & 0x3F);
    let ts_low = 0x80 | (ts13 as u8 & 0x7F);
    let ch = channel.saturating_sub(1) & 0x0F;
    [header, ts_low, 0x90 | ch, note & 0x7F, velocity & 0x7F]
}

/// Encode a 5-byte Apple BLE-MIDI Note-Off packet (`[header, timestamp, 0x8n, note, 0x00]`).
#[inline]
pub const fn encode_ble_midi_note_off(timestamp_ms: u16, channel: u8, note: u8) -> [u8; 5] {
    let ts13 = timestamp_ms & 0x1FFF;
    let header = 0x80 | ((ts13 >> 7) as u8 & 0x3F);
    let ts_low = 0x80 | (ts13 as u8 & 0x7F);
    let ch = channel.saturating_sub(1) & 0x0F;
    [header, ts_low, 0x80 | ch, note & 0x7F, 0x00]
}

/// Encode a 3-byte Apple BLE-MIDI Real-Time System message (`0xF8` Clock, `0xFA` Start, `0xFC` Stop).
#[inline]
pub const fn encode_ble_midi_realtime(timestamp_ms: u16, status_byte: u8) -> [u8; 3] {
    let ts13 = timestamp_ms & 0x1FFF;
    let header = 0x80 | ((ts13 >> 7) as u8 & 0x3F);
    let ts_low = 0x80 | (ts13 as u8 & 0x7F);
    [header, ts_low, status_byte]
}

/// Wrap a BLE-MIDI packet in an L2CAP + ATT Handle Value Notification (`0x1B`) on `HANDLE_MIDI_IO_VAL` (`0x000E`).
/// Returns `(l2cap_pdu, length)`.
pub fn build_midi_notification_l2cap(midi_payload: &[u8]) -> ([u8; 32], usize) {
    let mut buf = [0u8; 32];
    let att_len = 3 + midi_payload.len(); // Opcode (1) + Handle (2) + MIDI bytes
    let l2cap_len = (att_len as u16).to_le_bytes();
    let cid = L2CAP_CID_ATT.to_le_bytes();
    let handle = HANDLE_MIDI_IO_VAL.to_le_bytes();

    buf[0] = l2cap_len[0];
    buf[1] = l2cap_len[1];
    buf[2] = cid[0];
    buf[3] = cid[1];
    buf[4] = ATT_HANDLE_VALUE_NTF;
    buf[5] = handle[0];
    buf[6] = handle[1];

    let copy_len = midi_payload.len().min(25);
    buf[7..7 + copy_len].copy_from_slice(&midi_payload[..copy_len]);
    (buf, 7 + copy_len)
}

/// Parse an incoming BLE-MIDI write payload on `HANDLE_MIDI_IO_VAL` (`0x000E`) for custom configuration
/// SysEx messages (`F0 7D 4D 45 <param_id> <val_hi_7bit> <val_lo_7bit> F7`).
///
/// Note that in BLE-MIDI, a timestamp byte (`0x80..0xFF`) precedes `0xF0` and may also precede `0xF7`.
pub fn parse_ble_midi_config_sysex(
    ble_midi_bytes: &[u8],
    config: &mut BtMidiConfig,
) -> Option<(u8, u16)> {
    // Strip BLE-MIDI header/timestamp bytes (any byte >= 0x80 that isn't 0xF0 or 0xF7)
    let mut clean = [0u8; 16];
    let mut n = 0usize;
    let mut in_sysex = false;

    for &b in ble_midi_bytes {
        if b == 0xF0 {
            in_sysex = true;
            n = 0;
            clean[n] = b;
            n += 1;
        } else if in_sysex {
            if b == 0xF7 {
                if n < clean.len() {
                    clean[n] = b;
                    n += 1;
                }
                break;
            } else if (b & 0x80) == 0 {
                if n < clean.len() {
                    clean[n] = b;
                    n += 1;
                }
            }
            // Ignore embedded BLE-MIDI timestamp bytes (0x80..0xEF) before F7
        }
    }

    // Expected clean SysEx: [0xF0, 0x7D, 0x4D, 0x45, param_id, val_hi7, val_lo7, 0xF7]
    if n == 8 && clean[0] == 0xF0 && clean[1] == 0x7D && clean[2] == 0x4D && clean[3] == 0x45 && clean[7] == 0xF7
    {
        let param_id = clean[4];
        let val = ((clean[5] as u16) << 7) | (clean[6] as u16);
        if config.apply_sysex_param(param_id, val) {
            return Some((param_id, val));
        }
    }
    None
}

/// Stateful ATT / GATT Server for our BLE-MIDI Peripheral.
#[derive(Clone, Copy, Debug)]
pub struct BleMidiGattServer {
    pub client_mtu: u16,
    pub midi_cccd_enabled: bool,
    pub svc_changed_cccd: u16,
    pub att_req_count: u32,
    pub last_written_param: Option<(u8, u16)>,
}

impl Default for BleMidiGattServer {
    fn default() -> Self {
        Self::new()
    }
}

impl BleMidiGattServer {
    pub const fn new() -> Self {
        Self {
            client_mtu: 23,
            midi_cccd_enabled: false,
            svc_changed_cccd: 0,
            att_req_count: 0,
            last_written_param: None,
        }
    }

    pub fn reset_connection(&mut self) {
        self.client_mtu = 23;
        self.midi_cccd_enabled = false;
        self.svc_changed_cccd = 0;
    }

    /// Process an incoming L2CAP PDU (`l2cap_pdu` starts with `[len_lo, len_hi, cid_lo, cid_hi, ...]`)
    /// and return an optional L2CAP response PDU `(resp_buf, resp_len)`.
    pub fn handle_l2cap_pdu(
        &mut self,
        l2cap_pdu: &[u8],
        config: &mut BtMidiConfig,
    ) -> Option<([u8; MAX_DATA_PDU_PAYLOAD], usize)> {
        if l2cap_pdu.len() < 5 {
            return None;
        }
        let l2cap_len = u16::from_le_bytes([l2cap_pdu[0], l2cap_pdu[1]]) as usize;
        let cid = u16::from_le_bytes([l2cap_pdu[2], l2cap_pdu[3]]);
        let payload = &l2cap_pdu[4..l2cap_pdu.len().min(4 + l2cap_len)];

        if payload.is_empty() {
            return None;
        }

        if cid == L2CAP_CID_SMP {
            // If Central sends SMP Pairing Request (0x01) or Security Request, reply with
            // SMP Pairing Failed (0x05) reason 0x05 (Pairing Not Supported) so it proceeds unencrypted,
            // or ignore if not a Pairing Request.
            if payload[0] == 0x01 {
                return Some(Self::wrap_l2cap(L2CAP_CID_SMP, &[0x05, 0x05]));
            }
            return None;
        }

        if cid != L2CAP_CID_ATT {
            return None;
        }

        self.att_req_count = self.att_req_count.wrapping_add(1);
        let opcode = payload[0];
        let mut att_rsp = [0u8; 56];

        match opcode {
            ATT_EXCHANGE_MTU_REQ if payload.len() >= 3 => {
                let req_mtu = u16::from_le_bytes([payload[1], payload[2]]);
                let our_max_mtu: u16 = 56;
                self.client_mtu = req_mtu.clamp(23, our_max_mtu);
                let mtu_le = our_max_mtu.to_le_bytes();
                att_rsp[0] = ATT_EXCHANGE_MTU_RSP;
                att_rsp[1] = mtu_le[0];
                att_rsp[2] = mtu_le[1];
                Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..3]))
            }

            ATT_READ_BY_GROUP_TYPE_REQ if payload.len() >= 7 => {
                let start_h = u16::from_le_bytes([payload[1], payload[2]]);
                let end_h = u16::from_le_bytes([payload[3], payload[4]]);
                let group_uuid_is_primary =
                    payload.len() == 7 && payload[5] == 0x00 && payload[6] == 0x28;

                if !group_uuid_is_primary || start_h > end_h || start_h > HANDLE_MIDI_IO_CCCD {
                    return Some(Self::att_error(opcode, start_h, ATT_ERR_ATTR_NOT_FOUND));
                }

                // Group 1 & 2: 16-bit Primary Services (GAP 0x1800 at 0x0001..0x0007, GATT 0x1801 at 0x0008..0x000B)
                if start_h <= HANDLE_GATT_SERVICE {
                    att_rsp[0] = ATT_READ_BY_GROUP_TYPE_RSP;
                    att_rsp[1] = 6; // 2 (start) + 2 (end) + 2 (16-bit UUID)
                    let mut idx = 2usize;

                    if start_h <= HANDLE_GAP_SERVICE && end_h >= HANDLE_GAP_SERVICE {
                        att_rsp[idx..idx + 6].copy_from_slice(&[
                            0x01, 0x00, // Start: 0x0001
                            0x07, 0x00, // End:   0x0007
                            0x00, 0x18, // UUID:  0x1800 (GAP)
                        ]);
                        idx += 6;
                    }
                    if start_h <= HANDLE_GATT_SERVICE && end_h >= HANDLE_GATT_SERVICE {
                        att_rsp[idx..idx + 6].copy_from_slice(&[
                            0x08, 0x00, // Start: 0x0008
                            0x0B, 0x00, // End:   0x000B
                            0x01, 0x18, // UUID:  0x1801 (GATT)
                        ]);
                        idx += 6;
                    }
                    if idx > 2 {
                        return Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..idx]));
                    }
                }

                // Group 3: 128-bit BLE MIDI Primary Service (0x000C..0x000F)
                if start_h <= HANDLE_MIDI_SERVICE && end_h >= HANDLE_MIDI_SERVICE {
                    att_rsp[0] = ATT_READ_BY_GROUP_TYPE_RSP;
                    att_rsp[1] = 20; // 2 (start) + 2 (end) + 16 (128-bit UUID)
                    att_rsp[2] = 0x0C;
                    att_rsp[3] = 0x00;
                    att_rsp[4] = 0x0F;
                    att_rsp[5] = 0x00;
                    att_rsp[6..22].copy_from_slice(&BLE_MIDI_SERVICE_UUID_LE);
                    return Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..22]));
                }

                Some(Self::att_error(opcode, start_h, ATT_ERR_ATTR_NOT_FOUND))
            }

            ATT_FIND_BY_TYPE_VALUE_REQ if payload.len() >= 7 => {
                let start_h = u16::from_le_bytes([payload[1], payload[2]]);
                let end_h = u16::from_le_bytes([payload[3], payload[4]]);
                let attr_type = u16::from_le_bytes([payload[5], payload[6]]);
                let val = &payload[7..];

                if attr_type == 0x2800 {
                    // Searching for Primary Service by value
                    if val == [0x00, 0x18] && start_h <= 0x0001 && end_h >= 0x0001 {
                        return Some(Self::wrap_l2cap(
                            L2CAP_CID_ATT,
                            &[ATT_FIND_BY_TYPE_VALUE_RSP, 0x01, 0x00, 0x07, 0x00],
                        ));
                    }
                    if val == [0x01, 0x18] && start_h <= 0x0008 && end_h >= 0x0008 {
                        return Some(Self::wrap_l2cap(
                            L2CAP_CID_ATT,
                            &[ATT_FIND_BY_TYPE_VALUE_RSP, 0x08, 0x00, 0x0B, 0x00],
                        ));
                    }
                    if val == BLE_MIDI_SERVICE_UUID_LE && start_h <= 0x000C && end_h >= 0x000C {
                        return Some(Self::wrap_l2cap(
                            L2CAP_CID_ATT,
                            &[ATT_FIND_BY_TYPE_VALUE_RSP, 0x0C, 0x00, 0x0F, 0x00],
                        ));
                    }
                }
                Some(Self::att_error(opcode, start_h, ATT_ERR_ATTR_NOT_FOUND))
            }

            ATT_READ_BY_TYPE_REQ if payload.len() >= 7 => {
                let start_h = u16::from_le_bytes([payload[1], payload[2]]);
                let end_h = u16::from_le_bytes([payload[3], payload[4]]);

                if start_h > end_h || start_h > HANDLE_MIDI_IO_CCCD {
                    return Some(Self::att_error(opcode, start_h, ATT_ERR_ATTR_NOT_FOUND));
                }

                if payload.len() == 7 {
                    let uuid16 = u16::from_le_bytes([payload[5], payload[6]]);
                    match uuid16 {
                        0x2803 => {
                            // Characteristic Declarations
                            if start_h <= HANDLE_GATT_SVC_CHANGED_DECL {
                                att_rsp[0] = ATT_READ_BY_TYPE_RSP;
                                att_rsp[1] = 7; // 2 (decl handle) + 1 (props) + 2 (val handle) + 2 (uuid16)
                                let mut idx = 2usize;

                                let decls: [(u16, [u8; 5]); 4] = [
                                    (0x0002, [0x02, 0x03, 0x00, 0x00, 0x2A]), // Device Name
                                    (0x0004, [0x02, 0x05, 0x00, 0x01, 0x2A]), // Appearance
                                    (0x0006, [0x02, 0x07, 0x00, 0x04, 0x2A]), // PPCP
                                    (0x0009, [0x20, 0x0A, 0x00, 0x05, 0x2A]), // Service Changed
                                ];

                                for &(h, ref data) in &decls {
                                    if h >= start_h && h <= end_h && idx + 7 <= 23 {
                                        let h_le = h.to_le_bytes();
                                        att_rsp[idx] = h_le[0];
                                        att_rsp[idx + 1] = h_le[1];
                                        att_rsp[idx + 2..idx + 7].copy_from_slice(data);
                                        idx += 7;
                                    }
                                }
                                if idx > 2 {
                                    return Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..idx]));
                                }
                            }

                            // 128-bit BLE MIDI Characteristic Declaration at 0x000D
                            if start_h <= HANDLE_MIDI_IO_DECL && end_h >= HANDLE_MIDI_IO_DECL {
                                att_rsp[0] = ATT_READ_BY_TYPE_RSP;
                                att_rsp[1] = 21; // 2 (handle) + 1 (props 0x1E) + 2 (val handle 0x000E) + 16 (UUID)
                                att_rsp[2] = 0x0D;
                                att_rsp[3] = 0x00;
                                att_rsp[4] = 0x1E; // Read | WriteNoRsp | Write | Notify
                                att_rsp[5] = 0x0E;
                                att_rsp[6] = 0x00;
                                att_rsp[7..23].copy_from_slice(&BLE_MIDI_CHAR_UUID_LE);
                                return Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..23]));
                            }
                        }
                        0x2A00 => {
                            // Direct read of Device Name by UUID
                            if start_h <= HANDLE_GAP_NAME_VAL && end_h >= HANDLE_GAP_NAME_VAL {
                                let name = b"AI-METRO";
                                att_rsp[0] = ATT_READ_BY_TYPE_RSP;
                                att_rsp[1] = (2 + name.len()) as u8;
                                att_rsp[2] = 0x03;
                                att_rsp[3] = 0x00;
                                att_rsp[4..4 + name.len()].copy_from_slice(name);
                                return Some(Self::wrap_l2cap(
                                    L2CAP_CID_ATT,
                                    &att_rsp[..4 + name.len()],
                                ));
                            }
                        }
                        _ => {}
                    }
                }
                Some(Self::att_error(opcode, start_h, ATT_ERR_ATTR_NOT_FOUND))
            }

            ATT_FIND_INFO_REQ if payload.len() >= 5 => {
                let start_h = u16::from_le_bytes([payload[1], payload[2]]);
                let end_h = u16::from_le_bytes([payload[3], payload[4]]);

                if start_h <= HANDLE_GATT_SVC_CHANGED_CCCD && end_h >= HANDLE_GATT_SVC_CHANGED_CCCD
                    && start_h >= HANDLE_GATT_SVC_CHANGED_VAL
                {
                    // Return CCCD 0x2902 at handle 0x000B
                    return Some(Self::wrap_l2cap(
                        L2CAP_CID_ATT,
                        &[ATT_FIND_INFO_RSP, 0x01, 0x0B, 0x00, 0x02, 0x29],
                    ));
                }
                if start_h <= HANDLE_MIDI_IO_CCCD && end_h >= HANDLE_MIDI_IO_CCCD {
                    if start_h == HANDLE_MIDI_IO_VAL {
                        // Return 128-bit MIDI Char UUID at 0x000E
                        att_rsp[0] = ATT_FIND_INFO_RSP;
                        att_rsp[1] = 0x02; // Format: 128-bit UUID
                        att_rsp[2] = 0x0E;
                        att_rsp[3] = 0x00;
                        att_rsp[4..20].copy_from_slice(&BLE_MIDI_CHAR_UUID_LE);
                        return Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..20]));
                    }
                    // Return CCCD 0x2902 at handle 0x000F
                    return Some(Self::wrap_l2cap(
                        L2CAP_CID_ATT,
                        &[ATT_FIND_INFO_RSP, 0x01, 0x0F, 0x00, 0x02, 0x29],
                    ));
                }
                Some(Self::att_error(opcode, start_h, ATT_ERR_ATTR_NOT_FOUND))
            }

            ATT_READ_REQ | ATT_READ_BLOB_REQ if payload.len() >= 3 => {
                let handle = u16::from_le_bytes([payload[1], payload[2]]);
                let rsp_op = if opcode == ATT_READ_BLOB_REQ {
                    ATT_READ_BLOB_RSP
                } else {
                    ATT_READ_RSP
                };

                match handle {
                    HANDLE_GAP_NAME_VAL => {
                        let name = b"AI-METRO";
                        att_rsp[0] = rsp_op;
                        att_rsp[1..1 + name.len()].copy_from_slice(name);
                        Some(Self::wrap_l2cap(L2CAP_CID_ATT, &att_rsp[..1 + name.len()]))
                    }
                    HANDLE_GAP_APPEARANCE_VAL => {
                        Some(Self::wrap_l2cap(L2CAP_CID_ATT, &[rsp_op, 0x00, 0x00]))
                    }
                    HANDLE_GAP_PPCP_VAL => Some(Self::wrap_l2cap(
                        L2CAP_CID_ATT,
                        &[rsp_op, 0x06, 0x00, 0x0C, 0x00, 0x00, 0x00, 0xC8, 0x00],
                    )),
                    HANDLE_GATT_SVC_CHANGED_CCCD => {
                        let v = self.svc_changed_cccd.to_le_bytes();
                        Some(Self::wrap_l2cap(L2CAP_CID_ATT, &[rsp_op, v[0], v[1]]))
                    }
                    HANDLE_MIDI_IO_VAL => {
                        // Apple BLE-MIDI Spec Requirement:
                        // Read Request on MIDI I/O Characteristic MUST return a 0-byte payload!
                        Some(Self::wrap_l2cap(L2CAP_CID_ATT, &[rsp_op]))
                    }
                    HANDLE_MIDI_IO_CCCD => {
                        let v: u16 = if self.midi_cccd_enabled { 0x0001 } else { 0x0000 };
                        let v_le = v.to_le_bytes();
                        Some(Self::wrap_l2cap(L2CAP_CID_ATT, &[rsp_op, v_le[0], v_le[1]]))
                    }
                    _ => Some(Self::att_error(opcode, handle, ATT_ERR_INVALID_HANDLE)),
                }
            }

            ATT_WRITE_REQ | ATT_WRITE_CMD if payload.len() >= 3 => {
                let handle = u16::from_le_bytes([payload[1], payload[2]]);
                let val = &payload[3..];

                match handle {
                    HANDLE_MIDI_IO_CCCD => {
                        if !val.is_empty() {
                            self.midi_cccd_enabled = (val[0] & 0x01) != 0;
                        }
                    }
                    HANDLE_GATT_SVC_CHANGED_CCCD => {
                        if val.len() >= 2 {
                            self.svc_changed_cccd = u16::from_le_bytes([val[0], val[1]]);
                        }
                    }
                    HANDLE_MIDI_IO_VAL => {
                        if let Some(applied) = parse_ble_midi_config_sysex(val, config) {
                            self.last_written_param = Some(applied);
                        }
                    }
                    _ => {
                        if opcode == ATT_WRITE_REQ {
                            return Some(Self::att_error(opcode, handle, ATT_ERR_INVALID_HANDLE));
                        }
                        return None;
                    }
                }

                if opcode == ATT_WRITE_REQ {
                    Some(Self::wrap_l2cap(L2CAP_CID_ATT, &[ATT_WRITE_RSP]))
                } else {
                    None
                }
            }

            _ => {
                let h = if payload.len() >= 3 {
                    u16::from_le_bytes([payload[1], payload[2]])
                } else {
                    0x0000
                };
                Some(Self::att_error(opcode, h, ATT_ERR_REQ_NOT_SUPPORTED))
            }
        }
    }

    fn att_error(
        req_opcode: u8,
        handle: u16,
        err_code: u8,
    ) -> ([u8; MAX_DATA_PDU_PAYLOAD], usize) {
        let h = handle.to_le_bytes();
        Self::wrap_l2cap(
            L2CAP_CID_ATT,
            &[ATT_ERROR_RSP, req_opcode, h[0], h[1], err_code],
        )
    }

    fn wrap_l2cap(cid: u16, payload: &[u8]) -> ([u8; MAX_DATA_PDU_PAYLOAD], usize) {
        let mut out = [0u8; MAX_DATA_PDU_PAYLOAD];
        let copy_len = payload.len().min(MAX_DATA_PDU_PAYLOAD - 4);
        let len_le = (copy_len as u16).to_le_bytes();
        let cid_le = cid.to_le_bytes();
        out[0] = len_le[0];
        out[1] = len_le[1];
        out[2] = cid_le[0];
        out[3] = cid_le[1];
        out[4..4 + copy_len].copy_from_slice(&payload[..copy_len]);
        (out, 4 + copy_len)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_build_midi_adv_ind_pdu_fits_31_byte_advdata_limit() {
        let mac = [0x4A, 0x4D, 0x40, 0xCF, 0xE5, 0xEB];
        let (pdu, len) = build_midi_adv_ind_pdu(mac);
        assert_eq!(len, 39);
        assert_eq!(pdu[0], PDU_HEADER_ADV_IND_RANDOM);
        assert_eq!(pdu[1], 37); // 6 MAC + 31 AdvData
        assert_eq!(&pdu[13..29], &BLE_MIDI_SERVICE_UUID_LE);
        assert_eq!(&pdu[31..39], b"AI-METRO");
    }

    #[test]
    fn test_channel_hopper_csa1_with_remapping() {
        // Enable channels 0, 1, 2 only (bitmask 0b0000_0111)
        let ch_map = [0x07, 0x00, 0x00, 0x00, 0x00];
        let mut hopper = ChannelHopper::new(ch_map, 5);
        assert_eq!(hopper.num_used, 3);
        // Event 0: unmapped = (0 + 5) % 37 = 5 (unmapped) -> 5 % 3 = 2 -> used_channels[2] = 2
        assert_eq!(hopper.next_channel(), 2);
        // Event 1: unmapped = (5 + 5) % 37 = 10 (unmapped) -> 10 % 3 = 1 -> used_channels[1] = 1
        assert_eq!(hopper.next_channel(), 1);
    }

    #[test]
    fn test_ble_midi_note_and_clock_encoding() {
        let note_on = encode_ble_midi_note_on(0x1234, 10, 76, 120);
        // Header bit 7 = 1, bit 6 = 0
        assert_eq!(note_on[0] & 0xC0, 0x80);
        // Timestamp low bit 7 = 1
        assert_eq!(note_on[1] & 0x80, 0x80);
        // Channel 10 -> 0x99
        assert_eq!(note_on[2], 0x99);
        assert_eq!(note_on[3], 76);
        assert_eq!(note_on[4], 120);

        let clk = encode_ble_midi_realtime(500, MIDI_RT_TIMING_CLOCK);
        assert_eq!(clk.len(), 3);
        assert_eq!(clk[2], 0xF8);
    }

    #[test]
    fn test_gatt_server_discovery_and_apple_midi_zero_byte_read() {
        let mut gatt = BleMidiGattServer::new();
        let mut cfg = BtMidiConfig::new();

        // 1. Discover Primary Services (0x000C..0xFFFF) -> returns 128-bit BLE MIDI Service
        let req_svc = [0x07, 0x00, 0x04, 0x00, ATT_READ_BY_GROUP_TYPE_REQ, 0x0C, 0x00, 0xFF, 0xFF, 0x00, 0x28];
        let (rsp_svc, len_svc) = gatt.handle_l2cap_pdu(&req_svc, &mut cfg).unwrap();
        assert_eq!(len_svc, 4 + 22);
        assert_eq!(rsp_svc[4], ATT_READ_BY_GROUP_TYPE_RSP);
        assert_eq!(rsp_svc[5], 20);
        assert_eq!(&rsp_svc[10..26], &BLE_MIDI_SERVICE_UUID_LE);

        // 2. Read MIDI I/O Characteristic Value (Handle 0x000E) -> MUST return 0-byte payload ([0x0B])
        let req_read = [0x03, 0x00, 0x04, 0x00, ATT_READ_REQ, 0x0E, 0x00];
        let (rsp_read, len_read) = gatt.handle_l2cap_pdu(&req_read, &mut cfg).unwrap();
        assert_eq!(len_read, 5); // 4 L2CAP + 1 ATT_READ_RSP opcode (0 value bytes!)
        assert_eq!(rsp_read[4], ATT_READ_RSP);

        // 3. Enable CCCD Notification on Handle 0x000F
        assert!(!gatt.midi_cccd_enabled);
        let req_cccd = [0x05, 0x00, 0x04, 0x00, ATT_WRITE_REQ, 0x0F, 0x00, 0x01, 0x00];
        let (rsp_cccd, _) = gatt.handle_l2cap_pdu(&req_cccd, &mut cfg).unwrap();
        assert_eq!(rsp_cccd[4], ATT_WRITE_RSP);
        assert!(gatt.midi_cccd_enabled);

        // 4. Write Config SysEx to Handle 0x000E to set BPM = 145.0 (1450 -> hi7 = 11, lo7 = 42)
        let val: u16 = 1450;
        let hi7 = ((val >> 7) & 0x7F) as u8;
        let lo7 = (val & 0x7F) as u8;
        let req_sysex = [
            14, 0x00, 0x04, 0x00, ATT_WRITE_CMD, 0x0E, 0x00, 0x80, 0x80, 0xF0, 0x7D, 0x4D, 0x45,
            0x02, hi7, lo7, 0x80, 0xF7,
        ];
        let _ = gatt.handle_l2cap_pdu(&req_sysex, &mut cfg);
        assert!((cfg.bpm - 145.0).abs() < 0.01);
    }
}
