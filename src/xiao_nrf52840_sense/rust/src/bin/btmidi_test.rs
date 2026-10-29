//! Standalone Bluetooth Low Energy MIDI (BLE-MIDI) Sample Test App for Seeed Studio XIAO nRF52840 Sense.
//!
//! Advertises as a standard Apple / MMA BLE-MIDI Peripheral (`"AI-METRO"`, Service UUID
//! `03B80E5A-EDE8-4B33-A751-6CE34EC4C700`), accepts connections from **CME WIDI Jack**,
//! **iPad (Pianoteq / CoreMIDI)**, or **Chrome Web Bluetooth**, generates a configurable
//! fixed-tempo beat (`Note-On`/`Note-Off` + `24 PPQN 0xF8` Real-Time MIDI Clock), drives the
//! 8-LED NeoPixel stick (`D0` / `P0.02`) + onboard RGB LED, and streams rich live telemetry
//! over USB Serial (`COM10`) to the local HTML Configuration & Monitoring Dashboard.

#![no_std]
#![no_main]

#[allow(dead_code)]
#[path = "../hardware.rs"]
mod hardware;

use core::fmt::Write as FmtWrite;
use core::panic::PanicInfo;

use cortex_m_rt::{entry, exception};
use nrf52840_hal::clocks::Clocks;
use nrf52840_hal::pac::{self, NVIC, RADIO, SCB};
use nrf52840_hal::usbd::{UsbPeripheral, Usbd};
use usb_device::class_prelude::UsbBusAllocator;
use usb_device::device::{StringDescriptors, UsbDeviceBuilder, UsbDeviceState, UsbVidPid};
use usbd_serial::{SerialPort, USB_CLASS_CDC};

use ai_metronome_rust::ble_advertiser::{format_random_static_mac, BLE_ADV_CHANNELS};
use ai_metronome_rust::ble_midi::{
    build_midi_adv_ind_pdu, build_midi_notification_l2cap, build_midi_scan_rsp_pdu,
    data_channel_to_freq_mhz, encode_ble_midi_note_off, encode_ble_midi_note_on,
    encode_ble_midi_realtime, is_scan_req_for_us, parse_connect_ind, BleMidiGattServer,
    BtMidiConfig, ChannelHopper, ConnectIndParams, LLID_CONTINUED_OR_EMPTY, LLID_CONTROL,
    LLID_START_L2CAP, LL_CHANNEL_MAP_IND, LL_CONNECTION_UPDATE_IND, LL_ENC_REQ, LL_FEATURE_REQ,
    LL_FEATURE_RSP, LL_LENGTH_REQ, LL_LENGTH_RSP, LL_PING_REQ, LL_PING_RSP, LL_REJECT_IND,
    LL_SLAVE_FEATURE_REQ, LL_TERMINATE_IND, LL_UNKNOWN_RSP, LL_VERSION_IND, MAX_DATA_PDU_BUF,
    MAX_DATA_PDU_PAYLOAD, MIDI_RT_START, MIDI_RT_STOP, MIDI_RT_TIMING_CLOCK,
};
use ai_metronome_rust::mode_engine::LedColor;
use hardware::{
    feed_watchdog, init_watchdog, MonotonicTimer, RgbLedController, DFU_MAGIC_UF2_RESET,
};

const CLEAN_BOOT_FLAG_PTR: *mut u32 = 0x2003_FEFC as *mut u32;
const CLEAN_BOOT_MAGIC: u32 = 0xB007_C1EA;

/// Stack-allocated fixed buffer for `core::fmt::Write` formatting without `alloc`.
struct LineBuf<const N: usize> {
    buf: [u8; N],
    len: usize,
}

impl<const N: usize> LineBuf<N> {
    const fn new() -> Self {
        Self {
            buf: [0u8; N],
            len: 0,
        }
    }

    fn as_bytes(&self) -> &[u8] {
        &self.buf[..self.len]
    }
}

impl<const N: usize> FmtWrite for LineBuf<N> {
    fn write_str(&mut self, s: &str) -> core::fmt::Result {
        let bytes = s.as_bytes();
        let avail = N.saturating_sub(self.len);
        let to_copy = bytes.len().min(avail);
        self.buf[self.len..self.len + to_copy].copy_from_slice(&bytes[..to_copy]);
        self.len += to_copy;
        Ok(())
    }
}

#[panic_handler]
fn panic(_info: &PanicInfo) -> ! {
    SCB::sys_reset()
}

#[exception]
unsafe fn DefaultHandler(_irqn: i16) {
    (*cortex_m::peripheral::SYST::PTR).csr.write(0);
    (*SCB::PTR).icsr.write((1 << 25) | (1 << 27));
    let nvic = &*NVIC::PTR;
    for i in 0..8 {
        nvic.icer[i].write(0xFFFF_FFFF);
        nvic.icpr[i].write(0xFFFF_FFFF);
    }
}

/// Outgoing Link-Layer PDU queue entry (`llid` + payload bytes).
#[derive(Clone, Copy)]
struct TxQueueEntry {
    llid: u8,
    len: u8,
    payload: [u8; MAX_DATA_PDU_PAYLOAD],
}

impl TxQueueEntry {
    const fn empty() -> Self {
        Self {
            llid: LLID_CONTINUED_OR_EMPTY,
            len: 0,
            payload: [0u8; MAX_DATA_PDU_PAYLOAD],
        }
    }
}

/// Fixed-capacity ring buffer for outgoing BLE Link-Layer PDUs.
struct TxQueue<const CAP: usize> {
    entries: [TxQueueEntry; CAP],
    head: usize,
    tail: usize,
    count: usize,
}

impl<const CAP: usize> TxQueue<CAP> {
    const fn new() -> Self {
        Self {
            entries: [TxQueueEntry::empty(); CAP],
            head: 0,
            tail: 0,
            count: 0,
        }
    }

    fn clear(&mut self) {
        self.head = 0;
        self.tail = 0;
        self.count = 0;
    }

    fn is_empty(&self) -> bool {
        self.count == 0
    }

    fn push(&mut self, llid: u8, data: &[u8]) -> bool {
        if self.count >= CAP {
            return false;
        }
        let copy_len = data.len().min(MAX_DATA_PDU_PAYLOAD);
        let mut entry = TxQueueEntry::empty();
        entry.llid = llid;
        entry.len = copy_len as u8;
        entry.payload[..copy_len].copy_from_slice(&data[..copy_len]);
        self.entries[self.tail] = entry;
        self.tail = (self.tail + 1) % CAP;
        self.count += 1;
        true
    }

    fn pop(&mut self) -> Option<TxQueueEntry> {
        if self.count == 0 {
            return None;
        }
        let item = self.entries[self.head];
        self.head = (self.head + 1) % CAP;
        self.count -= 1;
        Some(item)
    }
}

/// Active BLE Link-Layer Connection State.
struct ActiveConnection {
    params: ConnectIndParams,
    hopper: ChannelHopper,
    current_channel: u8,
    conn_event_counter: u16,
    sn: u8,
    nesn: u8,
    has_inflight_tx: bool,
    inflight_entry: TxQueueEntry,
    first_packet_synced: bool,
    anchor_us: u64,
    interval_us: u64,
    timeout_us: u64,
    last_rx_us: u64,
    missed_events: u32,
    version_sent: bool,
    pending_conn_update: Option<(u8, u16, u16, u16, u16, u16)>,
    pending_ch_map_update: Option<([u8; 5], u16)>,
}

/// Configure `NRF_RADIO` for BLE 1 Mbps Advertising channels (`0x8E89BED6`).
fn configure_radio_advertising(radio: &RADIO) {
    radio.tasks_disable.write(|w| unsafe { w.bits(1) });
    let mut guard = 20_000u32;
    while radio.state.read().state().bits() != 0 && guard > 0 {
        guard -= 1;
    }

    radio.power.write(|w| w.power().enabled());
    radio.mode.write(|w| w.mode().ble_1mbit());
    radio.txpower.write(|w| w.txpower().pos4d_bm());

    // Advertising Access Address = 0x8E89BED6
    radio.base0.write(|w| unsafe { w.bits(0x89BE_D600) });
    radio.prefix0.write(|w| unsafe { w.ap0().bits(0x8E) });
    radio.txaddress.write(|w| unsafe { w.txaddress().bits(0) });
    radio.rxaddresses.write(|w| w.addr0().enabled());

    // PCNF0: S0 = 1 byte, LFLEN = 8 bits, S1 = 0 bits, PLEN = 8-bit
    radio.pcnf0.write(|w| unsafe {
        w.s0len()
            .set_bit()
            .lflen()
            .bits(8)
            .s1len()
            .bits(0)
            .plen()
            ._8bit()
    });

    // PCNF1: MAXLEN = 64 bytes, STATLEN = 0, BALEN = 3, Little Endian, Whitening Enabled
    radio.pcnf1.write(|w| unsafe {
        w.maxlen()
            .bits(MAX_DATA_PDU_PAYLOAD as u8)
            .statlen()
            .bits(0)
            .balen()
            .bits(3)
            .endian()
            .little()
            .whiteen()
            .enabled()
    });

    radio.crccnf.write(|w| w.len().three().skipaddr().skip());
    radio.crcpoly.write(|w| unsafe { w.crcpoly().bits(0x00065B) });
    radio.crcinit.write(|w| unsafe { w.crcinit().bits(0x555555) });

    // Default ramp-up mode (140 us) so hardware TIFS = 150 us is crystal-exact
    radio.modecnf0.write(|w| w.ru().default().dtx().center());
    radio.tifs.write(|w| unsafe { w.tifs().bits(150) });
    radio.shorts.reset();
}

/// Configure `NRF_RADIO` for an active BLE Data Channel connection.
fn configure_radio_connection(radio: &RADIO, access_address: u32, crc_init: u32) {
    radio.tasks_disable.write(|w| unsafe { w.bits(1) });
    let mut guard = 20_000u32;
    while radio.state.read().state().bits() != 0 && guard > 0 {
        guard -= 1;
    }

    radio
        .base0
        .write(|w| unsafe { w.bits(access_address << 8) });
    radio
        .prefix0
        .write(|w| unsafe { w.ap0().bits((access_address >> 24) as u8) });
    radio.txaddress.write(|w| unsafe { w.txaddress().bits(0) });
    radio.rxaddresses.write(|w| w.addr0().enabled());
    radio
        .crcinit
        .write(|w| unsafe { w.crcinit().bits(crc_init & 0x00FF_FFFF) });

    radio.modecnf0.write(|w| w.ru().default().dtx().center());
    radio.tifs.write(|w| unsafe { w.tifs().bits(150) });
    radio.shorts.reset();
}

/// Safely disable `NRF_RADIO` and wait until state reaches `DISABLED`.
#[inline]
fn stop_radio(radio: &RADIO) {
    radio.shorts.reset();
    radio.events_disabled.write(|w| unsafe { w.bits(0) });
    cortex_m::asm::dsb();
    radio.tasks_disable.write(|w| unsafe { w.bits(1) });
    let mut guard = 15_000u32;
    while radio.events_disabled.read().bits() == 0 && guard > 0 {
        guard -= 1;
    }
}

/// Write a slice over USB CDC Serial if configured and DTR is asserted.
fn usb_write_all<B: usb_device::bus::UsbBus>(
    usb_dev: &mut usb_device::device::UsbDevice<B>,
    serial: &mut SerialPort<B>,
    bytes: &[u8],
) {
    if usb_dev.state() != UsbDeviceState::Configured || !serial.dtr() {
        return;
    }
    let mut offset = 0usize;
    let mut retries = 0u32;
    while offset < bytes.len() && retries < 200 {
        let _ = usb_dev.poll(&mut [serial]);
        match serial.write(&bytes[offset..]) {
            Ok(n) if n > 0 => {
                offset += n;
                retries = 0;
            }
            _ => {
                retries += 1;
            }
        }
    }
}

#[entry]
fn main() -> ! {
    unsafe {
        cortex_m::interrupt::disable();
        (*cortex_m::peripheral::SYST::PTR).csr.write(0);
        (*SCB::PTR).icsr.write((1 << 25) | (1 << 27));
        let nvic = &*NVIC::PTR;
        for i in 0..8 {
            nvic.icer[i].write(0xFFFF_FFFF);
            nvic.icpr[i].write(0xFFFF_FFFF);
        }
        (*SCB::PTR).vtor.write(0x0002_7000);
        cortex_m::asm::dsb();
        cortex_m::asm::isb();

        if core::ptr::read_volatile(CLEAN_BOOT_FLAG_PTR) != CLEAN_BOOT_MAGIC {
            core::ptr::write_volatile(CLEAN_BOOT_FLAG_PTR, CLEAN_BOOT_MAGIC);
            cortex_m::asm::delay(12_800_000);
            cortex_m::asm::dsb();
            SCB::sys_reset();
        }
        core::ptr::write_volatile(CLEAN_BOOT_FLAG_PTR, 0);
    }

    let dp = pac::Peripherals::take().unwrap();

    // Initialize 64 MHz crystal HFXO for BLE radio & USB accuracy
    let clocks = Clocks::new(dp.CLOCK).enable_ext_hfosc();

    let mut timer = MonotonicTimer::new();
    timer.init(&dp.TIMER0);

    let mut leds = RgbLedController::new();
    leds.init(&dp.P0);

    init_watchdog(&dp.WDT);

    let usb_bus = UsbBusAllocator::new(Usbd::new(UsbPeripheral::new(dp.USBD, &clocks)));
    let mut serial = SerialPort::new(&usb_bus);
    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x2886, 0x0045))
        .strings(&[StringDescriptors::default()
            .manufacturer("Seeed Studio")
            .product("XIAO BLE-MIDI Test")
            .serial_number("XIAO-BTMIDI")])
        .unwrap()
        .device_class(USB_CLASS_CDC)
        .max_packet_size_0(64)
        .unwrap()
        .build();

    // Read factory BLE Random Static MAC Address
    let addr0 = dp.FICR.deviceaddr[0].read().bits();
    let addr1 = dp.FICR.deviceaddr[1].read().bits();
    let our_mac = format_random_static_mac(addr0, addr1);
    let (adv_ind_pdu, _adv_len) = build_midi_adv_ind_pdu(our_mac);
    let (scan_rsp_pdu, _scan_len) = build_midi_scan_rsp_pdu(our_mac);

    configure_radio_advertising(&dp.RADIO);

    // Quick startup NeoPixel sweep to confirm BLE-MIDI Test Mode
    leds.run_startup_pattern(&dp.P0, &mut timer, &dp.TIMER0, || {
        let _ = usb_dev.poll(&mut [&mut serial]);
    });

    let mut config = BtMidiConfig::new();
    let mut gatt = BleMidiGattServer::new();
    let mut tx_queue: TxQueue<16> = TxQueue::new();
    let mut conn: Option<ActiveConnection> = None;

    // Telemetry counters
    let mut adv_tx_count: u32 = 0;
    let mut scan_rsp_count: u32 = 0;
    let mut ll_rx_packets: u32 = 0;
    let mut ll_tx_packets: u32 = 0;
    let mut midi_notes_sent: u32 = 0;
    let mut midi_clocks_sent: u32 = 0;
    let mut last_midi_hex: [u8; 5] = [0; 5];
    let mut last_midi_len: usize = 0;

    // Beat & 24 PPQN Clock scheduling state
    let now0 = timer.now_us(&dp.TIMER0);
    let mut next_beat_us: u64 = now0 + 500_000;
    let mut next_clock_us: u64 = now0 + 20_833;
    let mut current_beat_in_bar: u8 = 0;
    let mut active_note_off: Option<(u64, u8, u8)> = None; // (deadline_us, ch, note)
    let mut manual_trigger_requested = false;

    let mut last_adv_us: u64 = now0;
    let mut last_status_us: u64 = now0;
    let mut banner_printed = false;
    let mut was_1200_armed = false;

    // Serial command line buffer
    let mut cmd_buf = [0u8; 96];
    let mut cmd_len = 0usize;
    let mut rx_pdu = [0u8; MAX_DATA_PDU_BUF];
    let mut tx_pdu = [0u8; MAX_DATA_PDU_BUF];

    loop {
        feed_watchdog(&dp.WDT);
        let _ = usb_dev.poll(&mut [&mut serial]);
        let now_us = timer.now_us(&dp.TIMER0);

        // 1. Service USB Serial input & 1200-baud bootloader reset
        if usb_dev.state() == UsbDeviceState::Configured {
            let rate = serial.line_coding().data_rate();
            let dtr = serial.dtr();
            if rate == 1200 {
                was_1200_armed = true;
            }
            if was_1200_armed && !dtr {
                dp.POWER
                    .gpregret
                    .write(|w| unsafe { w.bits(DFU_MAGIC_UF2_RESET as u32) });
                cortex_m::asm::dsb();
                SCB::sys_reset();
            }

            if dtr && !banner_printed {
                banner_printed = true;
                let mut lb = LineBuf::<192>::new();
                let _ = writeln!(
                    lb,
                    "\r\n[BTMIDI_READY] name=\"AI-METRO\" mac={:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X} uuid=03B80E5A-EDE8-4B33-A751-6CE34EC4C700\r",
                    our_mac[5], our_mac[4], our_mac[3], our_mac[2], our_mac[1], our_mac[0]
                );
                usb_write_all(&mut usb_dev, &mut serial, lb.as_bytes());
            } else if !dtr {
                banner_printed = false;
            }

            let mut usb_rx = [0u8; 32];
            if let Ok(n) = serial.read(&mut usb_rx) {
                for &b in &usb_rx[..n] {
                    if b == b'\n' || b == b'\r' {
                        if cmd_len > 0 {
                            if let Ok(line) = core::str::from_utf8(&cmd_buf[..cmd_len]) {
                                let trimmed = line.trim();
                                handle_serial_command(
                                    trimmed,
                                    &mut config,
                                    &mut conn,
                                    &dp.RADIO,
                                    &dp.POWER,
                                    &mut tx_queue,
                                    &mut gatt,
                                    &mut manual_trigger_requested,
                                    &mut last_status_us,
                                );
                            }
                            cmd_len = 0;
                        }
                    } else if cmd_len < cmd_buf.len() {
                        cmd_buf[cmd_len] = b;
                        cmd_len += 1;
                    }
                }
            }
        }

        // 2. BLE Radio State Machine: Either Connected or Advertising
        let mut safe_for_neopixel = true;

        if let Some(ref mut c) = conn {
            // Check Link Supervision Timeout
            if now_us.saturating_sub(c.last_rx_us) > c.timeout_us {
                let mut lb = LineBuf::<128>::new();
                let _ = writeln!(
                    lb,
                    "[BTMIDI_EVT] DISCONNECTED reason=TIMEOUT missed={}\r",
                    c.missed_events
                );
                usb_write_all(&mut usb_dev, &mut serial, lb.as_bytes());
                conn = None;
                gatt.reset_connection();
                tx_queue.clear();
                configure_radio_advertising(&dp.RADIO);
            } else {
                // Compute listening window around expected anchor point
                let early_margin_us: u64 = if !c.first_packet_synced {
                    450
                } else {
                    300 + (c.missed_events.min(10) as u64) * 60
                };
                let window_len_us: u64 = if !c.first_packet_synced {
                    ((c.params.win_size as u64).max(2)) * 1250 + 2500
                } else {
                    750 + (c.missed_events.min(10) as u64) * 120
                };

                let rx_open_us = c.anchor_us.saturating_sub(early_margin_us);
                // Avoid starting 300 us NeoPixel DMA within 1.5 ms of an upcoming BLE event
                if now_us + 1500 >= rx_open_us {
                    safe_for_neopixel = false;
                }

                if now_us >= rx_open_us {
                    let freq = data_channel_to_freq_mhz(c.current_channel);
                    dp.RADIO
                        .frequency
                        .write(|w| unsafe { w.frequency().bits(freq) });
                    dp.RADIO
                        .datawhiteiv
                        .write(|w| unsafe { w.datawhiteiv().bits(c.current_channel) });

                    rx_pdu[0] = 0;
                    rx_pdu[1] = 0;
                    dp.RADIO
                        .packetptr
                        .write(|w| unsafe { w.bits(rx_pdu.as_mut_ptr() as u32) });

                    // Hardware T_IFS turnaround: RX END -> DISABLE -> TXEN (150 us)
                    dp.RADIO.shorts.write(|w| {
                        w.ready_start()
                            .enabled()
                            .end_disable()
                            .enabled()
                            .disabled_txen()
                            .enabled()
                    });

                    dp.RADIO.events_address.write(|w| unsafe { w.bits(0) });
                    dp.RADIO.events_end.write(|w| unsafe { w.bits(0) });
                    dp.RADIO.events_disabled.write(|w| unsafe { w.bits(0) });
                    cortex_m::asm::dsb();
                    dp.RADIO.tasks_rxen.write(|w| unsafe { w.bits(1) });

                    let listen_start_us = timer.now_us(&dp.TIMER0);
                    let mut got_address = false;
                    while timer.now_us(&dp.TIMER0).wrapping_sub(listen_start_us) < window_len_us {
                        if dp.RADIO.events_address.read().bits() != 0 {
                            got_address = true;
                            break;
                        }
                    }

                    let mut disconnect_requested = false;

                    if got_address {
                        let rx_addr_us = timer.now_us(&dp.TIMER0);
                        // Wait for packet payload + CRC to finish
                        let mut end_guard = 35_000u32;
                        while dp.RADIO.events_end.read().bits() == 0 && end_guard > 0 {
                            end_guard -= 1;
                        }

                        if dp.RADIO.crcstatus.read().crcstatus().is_crcok() {
                            // Packet start was 40 us (1-byte preamble + 4-byte AA) before EVENTS_ADDRESS
                            let pkt_start_us = rx_addr_us.saturating_sub(40);
                            c.anchor_us = pkt_start_us;
                            c.last_rx_us = pkt_start_us;
                            c.first_packet_synced = true;
                            c.missed_events = 0;
                            ll_rx_packets = ll_rx_packets.wrapping_add(1);

                            let rx_s0 = rx_pdu[0];
                            let rx_len = (rx_pdu[1] as usize).min(MAX_DATA_PDU_PAYLOAD);
                            let rx_llid = rx_s0 & 0x03;
                            let rx_nesn = (rx_s0 >> 2) & 1;
                            let rx_sn = (rx_s0 >> 3) & 1;

                            // 1. Did Central ACK our last transmitted packet?
                            if rx_nesn != c.sn {
                                c.sn ^= 1;
                                c.has_inflight_tx = false;
                            }

                            // 2. Is this a new packet from Central?
                            let is_new_rx = rx_sn == c.nesn;
                            if is_new_rx {
                                c.nesn ^= 1;
                            }

                            // 3. Load next TX packet if not currently retransmitting
                            if !c.has_inflight_tx {
                                if let Some(next_entry) = tx_queue.pop() {
                                    c.inflight_entry = next_entry;
                                    c.has_inflight_tx = true;
                                }
                            }

                            // 4. Populate tx_pdu during the 140 us TX ramp-up window
                            let md_bit: u8 = if !tx_queue.is_empty() { 0x10 } else { 0x00 };
                            if c.has_inflight_tx {
                                let len = c.inflight_entry.len as usize;
                                tx_pdu[0] = (c.inflight_entry.llid & 0x03)
                                    | (c.nesn << 2)
                                    | (c.sn << 3)
                                    | md_bit;
                                tx_pdu[1] = len as u8;
                                tx_pdu[2..2 + len]
                                    .copy_from_slice(&c.inflight_entry.payload[..len]);
                            } else {
                                tx_pdu[0] =
                                    LLID_CONTINUED_OR_EMPTY | (c.nesn << 2) | (c.sn << 3);
                                tx_pdu[1] = 0;
                            }

                            dp.RADIO
                                .packetptr
                                .write(|w| unsafe { w.bits(tx_pdu.as_ptr() as u32) });
                            dp.RADIO
                                .shorts
                                .write(|w| w.ready_start().enabled().end_disable().enabled());
                            dp.RADIO.events_disabled.write(|w| unsafe { w.bits(0) });

                            // Wait for TX completion (~200-450 us)
                            let mut tx_guard = 40_000u32;
                            while dp.RADIO.events_disabled.read().bits() == 0 && tx_guard > 0 {
                                tx_guard -= 1;
                            }
                            if tx_guard == 0 {
                                stop_radio(&dp.RADIO);
                            } else {
                                ll_tx_packets = ll_tx_packets.wrapping_add(1);
                            }

                            // 5. Process incoming Link-Layer Control or L2CAP/ATT payload
                            if is_new_rx && rx_len > 0 {
                                let payload = &rx_pdu[2..2 + rx_len];
                                if rx_llid == LLID_CONTROL {
                                    let opcode = payload[0];
                                    match opcode {
                                        LL_VERSION_IND => {
                                            if !c.version_sent {
                                                c.version_sent = true;
                                                // VersNr 0x08 (BLE 4.2), CompId 0x0059 (Nordic), SubVers 0x0001
                                                let _ = tx_queue.push(
                                                    LLID_CONTROL,
                                                    &[LL_VERSION_IND, 0x08, 0x59, 0x00, 0x01, 0x00],
                                                );
                                            }
                                        }
                                        LL_FEATURE_REQ | LL_SLAVE_FEATURE_REQ => {
                                            let _ = tx_queue.push(
                                                LLID_CONTROL,
                                                &[
                                                    LL_FEATURE_RSP,
                                                    0x00,
                                                    0x00,
                                                    0x00,
                                                    0x00,
                                                    0x00,
                                                    0x00,
                                                    0x00,
                                                    0x00,
                                                ],
                                            );
                                        }
                                        LL_LENGTH_REQ => {
                                            // MaxRxOctets=64 (0x0040), MaxRxTime=600 (0x0258), MaxTxOctets=64, MaxTxTime=600
                                            let _ = tx_queue.push(
                                                LLID_CONTROL,
                                                &[
                                                    LL_LENGTH_RSP,
                                                    0x40,
                                                    0x00,
                                                    0x58,
                                                    0x02,
                                                    0x40,
                                                    0x00,
                                                    0x58,
                                                    0x02,
                                                ],
                                            );
                                        }
                                        LL_PING_REQ => {
                                            let _ = tx_queue.push(LLID_CONTROL, &[LL_PING_RSP]);
                                        }
                                        LL_CONNECTION_UPDATE_IND if payload.len() >= 12 => {
                                            let win_size = payload[1];
                                            let win_offset =
                                                u16::from_le_bytes([payload[2], payload[3]]);
                                            let interval =
                                                u16::from_le_bytes([payload[4], payload[5]]);
                                            let latency =
                                                u16::from_le_bytes([payload[6], payload[7]]);
                                            let timeout =
                                                u16::from_le_bytes([payload[8], payload[9]]);
                                            let instant =
                                                u16::from_le_bytes([payload[10], payload[11]]);
                                            c.pending_conn_update = Some((
                                                win_size, win_offset, interval, latency, timeout,
                                                instant,
                                            ));
                                        }
                                        LL_CHANNEL_MAP_IND if payload.len() >= 8 => {
                                            let new_map = [
                                                payload[1],
                                                payload[2],
                                                payload[3],
                                                payload[4],
                                                payload[5] & 0x1F,
                                            ];
                                            let instant =
                                                u16::from_le_bytes([payload[6], payload[7]]);
                                            c.pending_ch_map_update = Some((new_map, instant));
                                        }
                                        LL_ENC_REQ => {
                                            // Reject encryption with PIN/Key Missing (0x06) so Central uses unencrypted MIDI
                                            let _ =
                                                tx_queue.push(LLID_CONTROL, &[LL_REJECT_IND, 0x06]);
                                        }
                                        LL_TERMINATE_IND => {
                                            disconnect_requested = true;
                                        }
                                        _ => {
                                            let _ = tx_queue
                                                .push(LLID_CONTROL, &[LL_UNKNOWN_RSP, opcode]);
                                        }
                                    }
                                } else if rx_llid == LLID_START_L2CAP {
                                    let prev_cccd = gatt.midi_cccd_enabled;
                                    if let Some((rsp_buf, rsp_len)) =
                                        gatt.handle_l2cap_pdu(payload, &mut config)
                                    {
                                        let _ = tx_queue.push(LLID_START_L2CAP, &rsp_buf[..rsp_len]);
                                    }
                                    if !prev_cccd && gatt.midi_cccd_enabled {
                                        let mut lb = LineBuf::<96>::new();
                                        let _ = writeln!(
                                            lb,
                                            "[BTMIDI_EVT] GATT_SUBSCRIBED cccd=1 mtu={}\r",
                                            gatt.client_mtu
                                        );
                                        usb_write_all(&mut usb_dev, &mut serial, lb.as_bytes());
                                    }
                                }
                            }
                        } else {
                            // Bad CRC: abort automatic TX immediately
                            stop_radio(&dp.RADIO);
                            c.missed_events = c.missed_events.saturating_add(1);
                        }
                    } else {
                        // No packet received in listening window
                        stop_radio(&dp.RADIO);
                        c.missed_events = c.missed_events.saturating_add(1);
                    }

                    if disconnect_requested {
                        let mut lb = LineBuf::<96>::new();
                        let _ = writeln!(lb, "[BTMIDI_EVT] DISCONNECTED reason=PEER_TERMINATED\r");
                        usb_write_all(&mut usb_dev, &mut serial, lb.as_bytes());
                        conn = None;
                        gatt.reset_connection();
                        tx_queue.clear();
                        configure_radio_advertising(&dp.RADIO);
                    } else {
                        // Advance to the next BLE connection event
                        c.conn_event_counter = c.conn_event_counter.wrapping_add(1);
                        c.anchor_us = c.anchor_us.wrapping_add(c.interval_us);

                        // Apply scheduled Channel Map update if Instant reached
                        if let Some((new_map, instant)) = c.pending_ch_map_update {
                            if c.conn_event_counter == instant {
                                c.hopper.update_channel_map(new_map);
                                c.pending_ch_map_update = None;
                            }
                        }

                        // Apply scheduled Connection Parameter update if Instant reached
                        if let Some((win_size, win_offset, interval, latency, timeout, instant)) =
                            c.pending_conn_update
                        {
                            if c.conn_event_counter == instant {
                                c.anchor_us =
                                    c.anchor_us.wrapping_add((win_offset as u64) * 1250);
                                c.interval_us = (interval as u64) * 1250;
                                c.timeout_us = (timeout as u64) * 10_000;
                                c.params.win_size = win_size;
                                c.params.interval = interval;
                                c.params.latency = latency;
                                c.params.timeout = timeout;
                                c.first_packet_synced = false;
                                c.pending_conn_update = None;
                            }
                        }

                        c.current_channel = c.hopper.next_channel();
                        // Right after finishing a connection event, we have at least ~7 ms before the next event
                        safe_for_neopixel = true;
                    }
                }
            }
        } else {
            // Advertising Mode: Broadcast ADV_IND every 20 ms across channels 37, 38, 39
            if now_us.wrapping_sub(last_adv_us) >= 20_000 {
                last_adv_us = now_us;
                adv_tx_count = adv_tx_count.wrapping_add(1);

                for &(chan, freq_mhz) in &BLE_ADV_CHANNELS {
                    dp.RADIO
                        .frequency
                        .write(|w| unsafe { w.frequency().bits(freq_mhz) });
                    dp.RADIO
                        .datawhiteiv
                        .write(|w| unsafe { w.datawhiteiv().bits(chan) });

                    dp.RADIO
                        .packetptr
                        .write(|w| unsafe { w.bits(adv_ind_pdu.as_ptr() as u32) });

                    // TX ADV_IND -> END_DISABLE -> DISABLED_RXEN (listen at T_IFS = 150 us)
                    dp.RADIO.shorts.write(|w| {
                        w.ready_start()
                            .enabled()
                            .end_disable()
                            .enabled()
                            .disabled_rxen()
                            .enabled()
                    });

                    dp.RADIO.events_disabled.write(|w| unsafe { w.bits(0) });
                    cortex_m::asm::dsb();
                    dp.RADIO.tasks_txen.write(|w| unsafe { w.bits(1) });

                    // Wait for ADV_IND TX to finish (~450 us)
                    let mut tx_guard = 30_000u32;
                    while dp.RADIO.events_disabled.read().bits() == 0 && tx_guard > 0 {
                        tx_guard -= 1;
                    }

                    // Radio is now ramping up RX (140 us) for SCAN_REQ or CONNECT_IND!
                    rx_pdu[0] = 0;
                    rx_pdu[1] = 0;
                    dp.RADIO
                        .packetptr
                        .write(|w| unsafe { w.bits(rx_pdu.as_mut_ptr() as u32) });
                    dp.RADIO.shorts.write(|w| {
                        w.ready_start()
                            .enabled()
                            .end_disable()
                            .enabled()
                            .disabled_txen()
                            .enabled()
                    });
                    dp.RADIO.events_address.write(|w| unsafe { w.bits(0) });
                    dp.RADIO.events_end.write(|w| unsafe { w.bits(0) });
                    dp.RADIO.events_disabled.write(|w| unsafe { w.bits(0) });

                    let rx_wait_start = timer.now_us(&dp.TIMER0);
                    let mut got_req_addr = false;
                    while timer.now_us(&dp.TIMER0).wrapping_sub(rx_wait_start) < 230 {
                        if dp.RADIO.events_address.read().bits() != 0 {
                            got_req_addr = true;
                            break;
                        }
                    }

                    if !got_req_addr {
                        stop_radio(&dp.RADIO);
                        continue;
                    }

                    // Wait for SCAN_REQ or CONNECT_IND payload to finish
                    let mut end_guard = 25_000u32;
                    while dp.RADIO.events_end.read().bits() == 0 && end_guard > 0 {
                        end_guard -= 1;
                    }
                    let req_end_us = timer.now_us(&dp.TIMER0);

                    if dp.RADIO.crcstatus.read().crcstatus().is_crcok() {
                        if is_scan_req_for_us(&rx_pdu, &our_mac) {
                            // Transmit SCAN_RSP automatically at T_IFS = 150 us
                            dp.RADIO
                                .packetptr
                                .write(|w| unsafe { w.bits(scan_rsp_pdu.as_ptr() as u32) });
                            dp.RADIO
                                .shorts
                                .write(|w| w.ready_start().enabled().end_disable().enabled());
                            dp.RADIO.events_disabled.write(|w| unsafe { w.bits(0) });

                            let mut rsp_guard = 30_000u32;
                            while dp.RADIO.events_disabled.read().bits() == 0 && rsp_guard > 0 {
                                rsp_guard -= 1;
                            }
                            if rsp_guard == 0 {
                                stop_radio(&dp.RADIO);
                            } else {
                                scan_rsp_count = scan_rsp_count.wrapping_add(1);
                            }
                        } else if let Some(params) = parse_connect_ind(&rx_pdu, &our_mac) {
                            // CONNECT_IND received! Stop radio and enter Connected state
                            stop_radio(&dp.RADIO);
                            configure_radio_connection(
                                &dp.RADIO,
                                params.access_address,
                                params.crc_init,
                            );

                            let mut hopper = ChannelHopper::new(params.ch_map, params.hop);
                            let ch0 = hopper.next_channel();
                            let interval_us = (params.interval as u64) * 1250;
                            let timeout_us = ((params.timeout as u64) * 10_000).max(2_000_000);
                            let first_anchor_us =
                                req_end_us + 1250 + (params.win_offset as u64) * 1250;

                            gatt.reset_connection();
                            tx_queue.clear();

                            conn = Some(ActiveConnection {
                                params,
                                hopper,
                                current_channel: ch0,
                                conn_event_counter: 0,
                                sn: 0,
                                nesn: 0,
                                has_inflight_tx: false,
                                inflight_entry: TxQueueEntry::empty(),
                                first_packet_synced: false,
                                anchor_us: first_anchor_us,
                                interval_us,
                                timeout_us,
                                last_rx_us: req_end_us,
                                missed_events: 0,
                                version_sent: false,
                                pending_conn_update: None,
                                pending_ch_map_update: None,
                            });

                            let mut lb = LineBuf::<160>::new();
                            let _ = writeln!(
                                lb,
                                "[BTMIDI_EVT] CONNECTED peer={:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X} interval_ms={:.2} hop={} timeout_ms={}\r",
                                params.peer_mac[5],
                                params.peer_mac[4],
                                params.peer_mac[3],
                                params.peer_mac[2],
                                params.peer_mac[1],
                                params.peer_mac[0],
                                (params.interval as f32) * 1.25,
                                params.hop,
                                (params.timeout as u32) * 10
                            );
                            usb_write_all(&mut usb_dev, &mut serial, lb.as_bytes());
                            break;
                        } else {
                            stop_radio(&dp.RADIO);
                        }
                    } else {
                        stop_radio(&dp.RADIO);
                    }
                }
            }
        }

        // 3. Fixed-Beat & 24-PPQN MIDI Clock Generator
        let now_us = timer.now_us(&dp.TIMER0);
        let ts_ms = ((now_us / 1000) & 0x1FFF) as u16;
        let beat_period_us = ((60_000_000.0 / config.bpm.clamp(30.0, 240.0)) as u64).max(200_000);
        let clock_period_us = (beat_period_us / 24).max(8_000);

        // 3a. 24 PPQN Real-Time MIDI Timing Clock (0xF8)
        if config.running && config.send_clock && now_us >= next_clock_us {
            next_clock_us = next_clock_us.wrapping_add(clock_period_us);
            if now_us > next_clock_us + clock_period_us * 2 {
                next_clock_us = now_us + clock_period_us;
            }
            if conn.is_some() && gatt.midi_cccd_enabled {
                let clk_pkt = encode_ble_midi_realtime(ts_ms, MIDI_RT_TIMING_CLOCK);
                let (l2cap_buf, l2cap_len) = build_midi_notification_l2cap(&clk_pkt);
                if tx_queue.push(LLID_START_L2CAP, &l2cap_buf[..l2cap_len]) {
                    midi_clocks_sent = midi_clocks_sent.wrapping_add(1);
                }
            }
        }

        // 3b. Pending Note-Off Gate Expiry
        if let Some((off_deadline_us, off_ch, off_note)) = active_note_off {
            if now_us >= off_deadline_us {
                active_note_off = None;
                if conn.is_some() && gatt.midi_cccd_enabled {
                    let off_pkt = encode_ble_midi_note_off(ts_ms, off_ch, off_note);
                    let (l2cap_buf, l2cap_len) = build_midi_notification_l2cap(&off_pkt);
                    let _ = tx_queue.push(LLID_START_L2CAP, &l2cap_buf[..l2cap_len]);
                }
            }
        }

        // 3c. Beat Trigger (Fixed Tempo or Manual Single-Shot Test Note)
        let beat_due = config.running && now_us >= next_beat_us;
        if beat_due || manual_trigger_requested {
            if beat_due {
                next_beat_us = next_beat_us.wrapping_add(beat_period_us);
                if now_us > next_beat_us + beat_period_us {
                    next_beat_us = now_us + beat_period_us;
                }
            }
            manual_trigger_requested = false;

            let is_downbeat = current_beat_in_bar == 0;
            let beat_num = current_beat_in_bar + 1;
            current_beat_in_bar = (current_beat_in_bar + 1) % config.meter.max(1);

            let (note, vel) = if is_downbeat {
                (config.accent_note, config.accent_velocity)
            } else {
                (config.beat_note, config.beat_velocity)
            };

            if config.send_notes || !beat_due {
                let note_on_pkt = encode_ble_midi_note_on(ts_ms, config.midi_channel, note, vel);
                last_midi_hex = note_on_pkt;
                last_midi_len = 5;

                if conn.is_some() && gatt.midi_cccd_enabled {
                    let (l2cap_buf, l2cap_len) = build_midi_notification_l2cap(&note_on_pkt);
                    if tx_queue.push(LLID_START_L2CAP, &l2cap_buf[..l2cap_len]) {
                        midi_notes_sent = midi_notes_sent.wrapping_add(1);
                        active_note_off = Some((
                            now_us + (config.note_gate_ms as u64) * 1000,
                            config.midi_channel,
                            note,
                        ));
                    }
                }
            }

            // Flash onboard RGB LED & NeoPixel Stick for visual beat confirmation
            let color = if conn.is_some() && gatt.midi_cccd_enabled {
                if is_downbeat {
                    LedColor::Green
                } else {
                    LedColor::Blue
                }
            } else if is_downbeat {
                LedColor::Red
            } else {
                LedColor::White
            };
            leds.set_color(&dp.P0, color);
            leds.off_deadline_sec = (now_us as f64) * 1.0e-6 + 0.035;

            if safe_for_neopixel {
                let mut frame = [(0u8, 0u8, 0u8); 8];
                let pixel_idx = ((beat_num - 1) as usize) % 8;
                if is_downbeat {
                    frame[0] = (0, 255, 80);
                    frame[7] = (0, 255, 80);
                } else {
                    frame[pixel_idx] = (0, 140, 255);
                }
                leds.write_neopixel_frame(&dp.P0, &frame, 1.0);
            }
        }

        // Turn off LED pulse after 35 ms gate
        let now_sec = (now_us as f64) * 1.0e-6;
        if leds.active_color != LedColor::Off && now_sec >= leds.off_deadline_sec && safe_for_neopixel
        {
            leds.off(&dp.P0);
        }

        // 4. Emit Periodic Live Telemetry Line over USB Serial (every 400 ms)
        if now_us.wrapping_sub(last_status_us) >= 400_000 {
            last_status_us = now_us;
            let mut lb = LineBuf::<320>::new();
            let (state_str, peer_mac, interval_ms, data_ch) = if let Some(ref c) = conn {
                let st = if gatt.midi_cccd_enabled {
                    "SUBSCRIBED"
                } else {
                    "CONNECTED"
                };
                (
                    st,
                    c.params.peer_mac,
                    (c.params.interval as f32) * 1.25,
                    c.current_channel,
                )
            } else {
                ("ADVERTISING", [0u8; 6], 0.0, 37)
            };

            let beat_disp = (current_beat_in_bar % config.meter.max(1)) + 1;
            let _ = writeln!(
                lb,
                "[BTMIDI] STATE={} MAC={:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X} PEER={:02X}:{:02X}:{:02X}:{:02X}:{:02X}:{:02X} INT_MS={:.2} CH={} CCCD={} MTU={} BPM={:.1} METER={} BEAT={}/{} RUN={} CH_MIDI={} ACCENT={}:{} BEAT_NOTE={}:{} GATE={} NOTES={} CLK={} RX={} TX={} MIDI_TX={} CLK_TX={} ADV={} SCAN={} LAST_HEX={:02X}{:02X}{:02X}{:02X}{:02X}\r",
                state_str,
                our_mac[5], our_mac[4], our_mac[3], our_mac[2], our_mac[1], our_mac[0],
                peer_mac[5], peer_mac[4], peer_mac[3], peer_mac[2], peer_mac[1], peer_mac[0],
                interval_ms,
                data_ch,
                if gatt.midi_cccd_enabled { 1 } else { 0 },
                gatt.client_mtu,
                config.bpm,
                config.meter,
                beat_disp,
                config.meter,
                if config.running { 1 } else { 0 },
                config.midi_channel,
                config.accent_note,
                config.accent_velocity,
                config.beat_note,
                config.beat_velocity,
                config.note_gate_ms,
                if config.send_notes { 1 } else { 0 },
                if config.send_clock { 1 } else { 0 },
                ll_rx_packets,
                ll_tx_packets,
                midi_notes_sent,
                midi_clocks_sent,
                adv_tx_count,
                scan_rsp_count,
                last_midi_hex[0],
                last_midi_hex[1],
                last_midi_hex[2],
                last_midi_hex[3],
                if last_midi_len >= 5 { last_midi_hex[4] } else { 0 }
            );
            usb_write_all(&mut usb_dev, &mut serial, lb.as_bytes());
        }
    }
}

#[allow(clippy::too_many_arguments)]
fn handle_serial_command(
    cmd: &str,
    config: &mut BtMidiConfig,
    conn: &mut Option<ActiveConnection>,
    radio: &RADIO,
    power: &pac::POWER,
    tx_queue: &mut TxQueue<16>,
    gatt: &mut BleMidiGattServer,
    manual_trigger_requested: &mut bool,
    last_status_us: &mut u64,
) {
    if cmd.eq_ignore_ascii_case("BOOTLOADER") || cmd.eq_ignore_ascii_case("B") {
        power
            .gpregret
            .write(|w| unsafe { w.bits(DFU_MAGIC_UF2_RESET as u32) });
        cortex_m::asm::dsb();
        SCB::sys_reset();
    } else if cmd.eq_ignore_ascii_case("STATUS") {
        *last_status_us = 0;
    } else if cmd.eq_ignore_ascii_case("TRIG") {
        *manual_trigger_requested = true;
        *last_status_us = 0;
    } else if cmd.eq_ignore_ascii_case("DISCONNECT") {
        if conn.is_some() {
            *conn = None;
            gatt.reset_connection();
            tx_queue.clear();
            configure_radio_advertising(radio);
        }
        *last_status_us = 0;
    } else if cmd.eq_ignore_ascii_case("PRESET PIANOTEQ") {
        config.midi_channel = 1;
        config.accent_note = 84; // C6 crisp high note
        config.accent_velocity = 115;
        config.beat_note = 72; // C5 octave below
        config.beat_velocity = 75;
        config.note_gate_ms = 25;
        config.send_notes = true;
        config.send_clock = true;
        *last_status_us = 0;
    } else if cmd.eq_ignore_ascii_case("PRESET WIDI") {
        config.midi_channel = 10;
        config.accent_note = 76; // High Woodblock
        config.accent_velocity = 120;
        config.beat_note = 77; // Low Woodblock
        config.beat_velocity = 85;
        config.note_gate_ms = 25;
        config.send_notes = true;
        config.send_clock = true;
        *last_status_us = 0;
    } else if cmd.eq_ignore_ascii_case("PRESET CLOCK") {
        config.send_notes = false;
        config.send_clock = true;
        *last_status_us = 0;
    } else if let Some(rest) = cmd.strip_prefix("SET ") {
        if let Some((k, v)) = rest.split_once('=') {
            let key = k.trim();
            let val_str = v.trim();
            if key.eq_ignore_ascii_case("BPM") {
                if let Some(bpm_x10) = parse_decimal_x10(val_str) {
                    config.bpm = ((bpm_x10 as f32) * 0.1).clamp(30.0, 240.0);
                }
            } else if let Ok(num) = val_str.parse::<u16>() {
                if key.eq_ignore_ascii_case("RUN") {
                    let new_run = num != 0;
                    if new_run != config.running && conn.is_some() && gatt.midi_cccd_enabled {
                        let rt_byte = if new_run { MIDI_RT_START } else { MIDI_RT_STOP };
                        let pkt = encode_ble_midi_realtime(0, rt_byte);
                        let (l2cap_buf, l2cap_len) = build_midi_notification_l2cap(&pkt);
                        let _ = tx_queue.push(LLID_START_L2CAP, &l2cap_buf[..l2cap_len]);
                    }
                    config.running = new_run;
                } else if key.eq_ignore_ascii_case("METER") {
                    config.meter = (num as u8).clamp(1, 8);
                } else if key.eq_ignore_ascii_case("CH") {
                    config.midi_channel = (num as u8).clamp(1, 16);
                } else if key.eq_ignore_ascii_case("ACCENT") {
                    config.accent_note = (num as u8) & 0x7F;
                } else if key.eq_ignore_ascii_case("VEL_ACCENT") {
                    config.accent_velocity = (num as u8).clamp(1, 127);
                } else if key.eq_ignore_ascii_case("BEAT") {
                    config.beat_note = (num as u8) & 0x7F;
                } else if key.eq_ignore_ascii_case("VEL_BEAT") {
                    config.beat_velocity = (num as u8).clamp(1, 127);
                } else if key.eq_ignore_ascii_case("GATE") {
                    config.note_gate_ms = num.clamp(5, 250);
                } else if key.eq_ignore_ascii_case("NOTES") {
                    config.send_notes = num != 0;
                } else if key.eq_ignore_ascii_case("CLOCK") {
                    config.send_clock = num != 0;
                }
            }
            *last_status_us = 0;
        }
    }
}

/// Parse a decimal string like `"120"` or `"120.5"` into tenths (`1200` or `1205`) without float `FromStr` bloat.
fn parse_decimal_x10(s: &str) -> Option<u32> {
    if let Some((int_part, frac_part)) = s.split_once('.') {
        let i = int_part.parse::<u32>().ok()?;
        let f_digit = frac_part
            .bytes()
            .next()
            .and_then(|b| b.checked_sub(b'0'))
            .unwrap_or(0) as u32;
        Some(i * 10 + f_digit.min(9))
    } else {
        let i = s.parse::<u32>().ok()?;
        Some(i * 10)
    }
}
