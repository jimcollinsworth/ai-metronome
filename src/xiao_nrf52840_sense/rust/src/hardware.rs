//! Low-level nRF52840 Hardware Drivers for Seeed Studio XIAO nRF52840 Sense.
//!
//! Directly controls `NRF_CLOCK`, `NRF_TIMER0` (1 MHz / 1 us monotonic clock),
//! `NRF_P0`/`NRF_P1` (Active-Low RGB LED + High-Drive sensor power gates),
//! `NRF_SAADC` (Battery voltage divider on P0.31/AIN7 with P0.14 sink gate),
//! `NRF_TEMP` (Die temperature), `NRF_PDM` (16 kHz double-buffered EasyDMA mic),
//! `NRF_TWIM0` (400 kHz I2C for LSM6DS3TR-C IMU), and `NRF_WDT` (5s Watchdog).

#![allow(clippy::needless_range_loop)]

use nrf52840_hal::pac::{
    p0, FICR, P0, P1, PDM, POWER, RADIO, SAADC, SCB, TEMP, TIMER0, TWIM0, WDT,
};

use ai_metronome_rust::ble_advertiser::{
    build_tempo_adv_pdu, format_random_static_mac, BLE_ADV_CHANNELS, MAX_BLE_PDU_LEN,
};
use ai_metronome_rust::mode_engine::{LedColor, PRE_LOCK_BRIGHTNESS, WEAK_BEAT_RED_BRIGHTNESS};

/// Adafruit UF2 Bootloader magic value in `NRF_POWER->GPREGRET` to enter UF2 DFU mode.
pub const DFU_MAGIC_UF2_RESET: u8 = 0x57;

/// LSM6DS3TR-C I2C address & registers.
pub const LSM6DS3_ADDR_PRIMARY: u8 = 0x6A;
pub const LSM6DS3_ADDR_ALT: u8 = 0x6B;
pub const REG_WHO_AM_I: u8 = 0x0F;
pub const REG_CTRL1_XL: u8 = 0x10;
pub const REG_CTRL2_G: u8 = 0x11;
pub const REG_CTRL3_C: u8 = 0x12;
pub const REG_OUTX_L_G: u8 = 0x22;
pub const REG_OUTX_L_XL: u8 = 0x28;
pub const REG_TAP_CFG: u8 = 0x58;
pub const REG_WAKE_UP_THS: u8 = 0x5B;
pub const REG_WAKE_UP_DUR: u8 = 0x5C;
pub const REG_MD1_CFG: u8 = 0x5E;
pub const WHO_AM_I_EXPECTED: u8 = 0x6A;

/// PDM frame size: 80 samples at 16 kHz = 5.0 ms per buffer.
pub const PDM_FRAME_SAMPLES: usize = 80;

/// 64-bit microsecond monotonic clock backed by 32-bit `NRF_TIMER0` @ 1 MHz.
pub struct MonotonicTimer {
    last_raw: u32,
    high_bits: u64,
}

impl MonotonicTimer {
    pub const fn new() -> Self {
        Self {
            last_raw: 0,
            high_bits: 0,
        }
    }

    pub fn init(&mut self, timer0: &TIMER0) {
        timer0.tasks_stop.write(|w| unsafe { w.bits(1) });
        timer0.tasks_clear.write(|w| unsafe { w.bits(1) });
        timer0.mode.write(|w| w.mode().timer());
        timer0.bitmode.write(|w| w.bitmode()._32bit());
        // 16 MHz / 2^4 = 1 MHz (1 tick = 1.0 us)
        timer0.prescaler.write(|w| unsafe { w.prescaler().bits(4) });
        timer0.tasks_start.write(|w| unsafe { w.bits(1) });
        self.last_raw = 0;
        self.high_bits = 0;
    }

    #[inline]
    pub fn now_us(&mut self, timer0: &TIMER0) -> u64 {
        timer0.tasks_capture[0].write(|w| unsafe { w.bits(1) });
        let raw = timer0.cc[0].read().bits();
        if raw < self.last_raw {
            self.high_bits += 1u64 << 32;
        }
        self.last_raw = raw;
        self.high_bits | (raw as u64)
    }

    #[inline]
    pub fn now_sec(&mut self, timer0: &TIMER0) -> f64 {
        (self.now_us(timer0) as f64) * 1.0e-6
    }

    pub fn delay_us(&mut self, timer0: &TIMER0, us: u64) {
        self.delay_us_with_poll(timer0, us, || {});
    }

    pub fn delay_us_with_poll<F: FnMut()>(&mut self, timer0: &TIMER0, us: u64, mut poll_fn: F) {
        let start = self.now_us(timer0);
        while self.now_us(timer0).wrapping_sub(start) < us {
            poll_fn();
            cortex_m::asm::nop();
        }
    }

    pub fn delay_ms(&mut self, timer0: &TIMER0, ms: u32) {
        self.delay_us(timer0, (ms as u64) * 1000);
    }

    pub fn delay_ms_with_poll<F: FnMut()>(&mut self, timer0: &TIMER0, ms: u32, poll_fn: F) {
        self.delay_us_with_poll(timer0, (ms as u64) * 1000, poll_fn);
    }
}

/// Active-Low RGB LED controller (`P0.26` Red, `P0.30` Green, `P0.06` Blue).
pub struct RgbLedController {
    pub off_deadline_sec: f64,
    pub active_color: LedColor,
}

impl RgbLedController {
    pub const PIN_RED: usize = 26;
    pub const PIN_GREEN: usize = 30;
    pub const PIN_BLUE: usize = 6;

    pub const fn new() -> Self {
        Self {
            off_deadline_sec: 0.0,
            active_color: LedColor::Off,
        }
    }

    pub fn init(&mut self, p0: &p0::RegisterBlock) {
        // Set HIGH (OFF for active-low LEDs) before configuring as output
        p0.outset.write(|w| unsafe {
            w.bits((1 << Self::PIN_RED) | (1 << Self::PIN_GREEN) | (1 << Self::PIN_BLUE))
        });
        for &pin in &[Self::PIN_RED, Self::PIN_GREEN, Self::PIN_BLUE] {
            p0.pin_cnf[pin].write(|w| {
                w.dir()
                    .output()
                    .input()
                    .disconnect()
                    .pull()
                    .disabled()
                    .drive()
                    .s0s1()
            });
        }
        self.active_color = LedColor::Off;
    }

    #[inline]
    pub fn set_raw(&mut self, p0: &p0::RegisterBlock, r_on: bool, g_on: bool, b_on: bool) {
        let mut set_mask: u32 = 0; // HIGH = OFF
        let mut clr_mask: u32 = 0; // LOW = ON

        if r_on {
            clr_mask |= 1 << Self::PIN_RED;
        } else {
            set_mask |= 1 << Self::PIN_RED;
        }
        if g_on {
            clr_mask |= 1 << Self::PIN_GREEN;
        } else {
            set_mask |= 1 << Self::PIN_GREEN;
        }
        if b_on {
            clr_mask |= 1 << Self::PIN_BLUE;
        } else {
            set_mask |= 1 << Self::PIN_BLUE;
        }

        if set_mask != 0 {
            p0.outset.write(|w| unsafe { w.bits(set_mask) });
        }
        if clr_mask != 0 {
            p0.outclr.write(|w| unsafe { w.bits(clr_mask) });
        }
    }

    pub fn set_color(&mut self, p0: &p0::RegisterBlock, color: LedColor) {
        self.active_color = color;
        match color {
            LedColor::Off => self.set_raw(p0, false, false, false),
            LedColor::Red => self.set_raw(p0, true, false, false),
            LedColor::Green => self.set_raw(p0, false, true, false),
            LedColor::Blue => self.set_raw(p0, false, false, true),
            LedColor::White => self.set_raw(p0, true, true, true),
        }
    }

    pub fn off(&mut self, p0: &p0::RegisterBlock) {
        self.off_deadline_sec = 0.0;
        self.set_color(p0, LedColor::Off);
    }

    /// Start a non-blocking LED flash with retinal pulse-width dimming matching v2.6:
    /// - Pre-lock (`brightness <= 0.19`): `12 ms` short pulse
    /// - Weak-beat Red in 3/4 & 4/4 (`brightness <= 0.25`): `15 ms` short pulse
    /// - Full locked downbeat / beat (`brightness > 0.25`): `130 ms` full pulse
    pub fn start_flash(
        &mut self,
        p0: &p0::RegisterBlock,
        color: LedColor,
        brightness: f32,
        now_sec: f64,
    ) {
        if color == LedColor::Off || brightness <= 0.0 {
            self.off(p0);
            return;
        }
        let pulse_sec = if brightness <= PRE_LOCK_BRIGHTNESS + 0.01 {
            0.012
        } else if brightness <= WEAK_BEAT_RED_BRIGHTNESS + 0.05 {
            0.015
        } else {
            0.130
        };
        self.set_color(p0, color);
        self.off_deadline_sec = now_sec + pulse_sec;
    }

    #[inline]
    pub fn poll(&mut self, p0: &p0::RegisterBlock, now_sec: f64) {
        if self.active_color != LedColor::Off
            && self.off_deadline_sec > 0.0
            && now_sec >= self.off_deadline_sec
        {
            self.off(p0);
        }
    }

    /// 3 Green blinks on successful startup calibration (`signal_init_ok`).
    #[allow(dead_code)]
    pub fn signal_init_ok(&mut self, p0: &p0::RegisterBlock, timer: &mut MonotonicTimer, timer0: &TIMER0) {
        self.off(p0);
        for _ in 0..3 {
            self.set_color(p0, LedColor::Green);
            timer.delay_ms(timer0, 90);
            self.off(p0);
            timer.delay_ms(timer0, 90);
        }
    }

    /// Visual confirmation on mode switch:
    /// 1) 350 ms Bright White burst (all 3 RGB diodes ON)
    /// 2) 220 ms dark pause
    /// 3) `mode_num` (1..4) distinct pulses in the new mode's color
    #[allow(dead_code)]
    pub fn signal_mode_change(
        &mut self,
        p0: &p0::RegisterBlock,
        timer: &mut MonotonicTimer,
        timer0: &TIMER0,
        mode_num: u8,
        confirm_color: LedColor,
    ) {
        self.off(p0);
        self.set_color(p0, LedColor::White);
        timer.delay_ms(timer0, 350);
        self.off(p0);
        timer.delay_ms(timer0, 220);

        for _ in 0..mode_num {
            self.set_color(p0, confirm_color);
            timer.delay_ms(timer0, 140);
            self.off(p0);
            timer.delay_ms(timer0, 140);
        }
    }

    /// Smooth Blue fade-down before entering 30s inactivity sleep.
    pub fn fade_blue_to_sleep(&mut self, p0: &p0::RegisterBlock, timer: &mut MonotonicTimer, timer0: &TIMER0) {
        self.off(p0);
        // 16-step software PWM ramp-down over ~320 ms (20 ms per step)
        for step in (0..16).rev() {
            let on_us = (step as u64) * 1000; // 15 ms .. 0 ms out of 20 ms
            let off_us = 20_000u64.saturating_sub(on_us);
            if on_us > 0 {
                self.set_color(p0, LedColor::Blue);
                timer.delay_us(timer0, on_us);
            }
            self.off(p0);
            if off_us > 0 {
                timer.delay_us(timer0, off_us);
            }
        }
        self.off(p0);
    }

    /// 2 crisp Green blinks upon waking from sleep (`signal_wake`).
    pub fn signal_wake(&mut self, p0: &p0::RegisterBlock, timer: &mut MonotonicTimer, timer0: &TIMER0) {
        self.off(p0);
        for _ in 0..2 {
            self.set_color(p0, LedColor::Green);
            timer.delay_ms(timer0, 75);
            self.off(p0);
            timer.delay_ms(timer0, 75);
        }
    }
}

/// Configure and start hardware watchdog (`NRF_WDT`) with a 5.0-second timeout,
/// paused during CPU `WFI` sleep and debugger halt.
pub fn init_watchdog(wdt: &WDT) {
    // 32768 Hz * 5 seconds = 163840 ticks
    wdt.crv.write(|w| unsafe { w.bits(32_768 * 5) });
    wdt.config.write(|w| w.sleep().pause().halt().pause());
    wdt.rren.write(|w| w.rr0().enabled());
    wdt.tasks_start.write(|w| unsafe { w.bits(1) });
}

#[inline]
pub fn feed_watchdog(wdt: &WDT) {
    wdt.rr[0].write(|w| unsafe { w.bits(0x6E52_4635) });
}

/// Inspect and clear `NRF_POWER->RESETREAS` to report why the MCU booted.
pub fn read_and_clear_reset_reason(power: &POWER) -> &'static str {
    let reas = power.resetreas.read();
    let reason = if reas.dog().is_detected() {
        "WATCHDOG_RESET"
    } else if reas.sreq().is_detected() {
        "SOFT_RESET"
    } else if reas.resetpin().is_detected() {
        "RESET_PIN"
    } else if reas.lockup().is_detected() {
        "CPU_LOCKUP"
    } else {
        "POWER_ON"
    };
    power.resetreas.write(|w| unsafe { w.bits(0xFFFF_FFFF) });
    reason
}

/// Trigger immediate reboot into the factory `XIAO-SENSE` UF2 bootloader.
pub fn reboot_to_uf2_bootloader(power: &POWER) -> ! {
    power.gpregret.write(|w| unsafe { w.bits(DFU_MAGIC_UF2_RESET as u32) });
    cortex_m::asm::dsb();
    SCB::sys_reset()
}

/// Read battery voltage (`V`), estimated percentage (`0..100%`), charge status (`P0.17`),
/// and CPU die temperature (`°C`).
pub struct PowerDiagReport {
    pub v_batt: f32,
    pub batt_pct: u8,
    pub is_charging: bool,
    pub die_temp_c: f32,
}

pub fn read_power_diagnostics(
    p0: &P0,
    saadc: &SAADC,
    temp: &TEMP,
    timer: &mut MonotonicTimer,
    timer0: &TIMER0,
) -> PowerDiagReport {
    // 1. Charge status on P0.17 (active-low: LOW = Charging)
    p0.pin_cnf[17].write(|w| {
        w.dir()
            .input()
            .input()
            .connect()
            .pull()
            .pullup()
            .drive()
            .s0s1()
    });
    timer.delay_us(timer0, 50);
    let is_charging = (p0.in_.read().bits() & (1 << 17)) == 0;

    // 2. Battery voltage divider enable on P0.14 (LOW = enabled)
    p0.outclr.write(|w| unsafe { w.bits(1 << 14) });
    p0.pin_cnf[14].write(|w| {
        w.dir()
            .output()
            .input()
            .disconnect()
            .pull()
            .disabled()
            .drive()
            .s0s1()
    });
    timer.delay_ms(timer0, 3);

    // 3. Configure SAADC channel 0 for P0.31 (AIN7), Gain 1/6, Internal 0.6V ref (3.6V FS), 12-bit
    saadc.enable.write(|w| w.enable().enabled());
    saadc.resolution.write(|w| w.val()._12bit());
    saadc.oversample.write(|w| w.oversample().bypass());
    saadc.ch[0].pselp.write(|w| w.pselp().analog_input7());
    saadc.ch[0].pseln.write(|w| w.pseln().nc());
    saadc.ch[0].config.write(|w| {
        w.resp()
            .bypass()
            .resn()
            .bypass()
            .gain()
            .gain1_6()
            .refsel()
            .internal()
            .tacq()
            ._10us()
            .mode()
            .se()
    });

    let mut adc_sample: i16 = 0;
    saadc
        .result
        .ptr
        .write(|w| unsafe { w.bits((&mut adc_sample as *mut i16) as u32) });
    saadc.result.maxcnt.write(|w| unsafe { w.bits(1) });

    saadc.events_started.write(|w| unsafe { w.bits(0) });
    saadc.tasks_start.write(|w| unsafe { w.bits(1) });
    let mut adc_guard = 50_000u32;
    while saadc.events_started.read().bits() == 0 && adc_guard > 0 {
        adc_guard -= 1;
    }

    saadc.events_end.write(|w| unsafe { w.bits(0) });
    saadc.tasks_sample.write(|w| unsafe { w.bits(1) });
    adc_guard = 50_000;
    while saadc.events_end.read().bits() == 0 && adc_guard > 0 {
        adc_guard -= 1;
    }

    saadc.events_stopped.write(|w| unsafe { w.bits(0) });
    saadc.tasks_stop.write(|w| unsafe { w.bits(1) });
    adc_guard = 50_000;
    while saadc.events_stopped.read().bits() == 0 && adc_guard > 0 {
        adc_guard -= 1;
    }
    saadc.enable.write(|w| w.enable().disabled());

    // Disable divider sink (set P0.14 HIGH / disconnected) to prevent battery drain
    p0.outset.write(|w| unsafe { w.bits(1 << 14) });
    p0.pin_cnf[14].write(|w| w.dir().input().input().disconnect());

    let raw_pos = adc_sample.max(0) as f32;
    let v_pin = (raw_pos / 4096.0) * 3.6;
    let v_batt = v_pin * (1510.0 / 510.0);
    let pct_f = ((v_batt - 3.30) / (4.20 - 3.30) * 100.0).clamp(0.0, 100.0);
    let batt_pct = pct_f as u8;

    // 4. CPU Die Temperature via NRF_TEMP (0.25 C steps)
    temp.events_datardy.write(|w| unsafe { w.bits(0) });
    temp.tasks_start.write(|w| unsafe { w.bits(1) });
    let mut timeout = 50_000u32;
    while temp.events_datardy.read().bits() == 0 && timeout > 0 {
        timeout -= 1;
    }
    let die_temp_c = if timeout > 0 {
        (temp.temp.read().bits() as i32 as f32) * 0.25
    } else {
        25.0
    };
    temp.tasks_stop.write(|w| unsafe { w.bits(1) });

    PowerDiagReport {
        v_batt,
        batt_pct,
        is_charging,
        die_temp_c,
    }
}

/// PDM Digital Microphone EasyDMA Driver (`P1.10` `MIC_PWR`, `P1.00` `PDM_CLK`, `P0.16` `PDM_DATA`).
pub struct PdmMicDriver {
    pub is_running: bool,
}

impl PdmMicDriver {
    pub const PIN_MIC_PWR_P1: usize = 10; // P1.10
    pub const PIN_PDM_CLK_P1: usize = 0;  // P1.00
    pub const PIN_PDM_DIN_P0: usize = 16; // P0.16

    pub const fn new() -> Self {
        Self { is_running: false }
    }

    /// Enable `P1.10` (`MIC_PWR`) with High Drive (`H0H1`) and configure `NRF_PDM` at 16 kHz mono.
    pub fn init_with_poll<F: FnMut()>(
        &mut self,
        p0: &P0,
        p1: &P1,
        pdm: &PDM,
        timer: &mut MonotonicTimer,
        timer0: &TIMER0,
        poll_fn: F,
    ) {
        // 1. Power up MIC_PWR (P1.10) with H0H1 high drive
        p1.outset.write(|w| unsafe { w.bits(1 << Self::PIN_MIC_PWR_P1) });
        p1.pin_cnf[Self::PIN_MIC_PWR_P1].write(|w| {
            w.dir()
                .output()
                .input()
                .disconnect()
                .pull()
                .disabled()
                .drive()
                .h0h1()
        });
        timer.delay_ms_with_poll(timer0, 30, poll_fn);

        // 2. Configure PDM_CLK (P1.00) as output and PDM_DIN (P0.16) as input
        p1.pin_cnf[Self::PIN_PDM_CLK_P1].write(|w| {
            w.dir()
                .output()
                .input()
                .disconnect()
                .pull()
                .disabled()
                .drive()
                .s0s1()
        });
        p0.pin_cnf[Self::PIN_PDM_DIN_P0].write(|w| {
            w.dir()
                .input()
                .input()
                .connect()
                .pull()
                .disabled()
                .drive()
                .s0s1()
        });

        // 3. Configure NRF_PDM registers for 16 kHz Mono
        pdm.enable.write(|w| w.enable().disabled());
        // P1.00 -> port 1, pin 0
        pdm.psel.clk.write(|w| unsafe {
            w.pin()
                .bits(Self::PIN_PDM_CLK_P1 as u8)
                .port()
                .bit(true)
                .connect()
                .connected()
        });
        // P0.16 -> port 0, pin 16
        pdm.psel.din.write(|w| unsafe {
            w.pin()
                .bits(Self::PIN_PDM_DIN_P0 as u8)
                .port()
                .bit(false)
                .connect()
                .connected()
        });

        // 1.032 MHz PDM clock / 64 = ~16.125 kHz PCM sample rate
        pdm.pdmclkctrl.write(|w| w.freq().default());
        pdm.mode.write(|w| w.operation().mono().edge().left_falling());
        pdm.gainl.write(|w| w.gainl().default_gain());
        pdm.gainr.write(|w| w.gainr().default_gain());

        pdm.enable.write(|w| w.enable().enabled());
        self.is_running = true;
    }

    /// Capture a single 80-sample (`5 ms` @ 16 kHz) PCM frame via EasyDMA.
    /// Runs `poll_fn` continuously while waiting for DMA completion to maintain microsecond USB latency.
    pub fn capture_frame_with_poll<F: FnMut()>(
        &mut self,
        pdm: &PDM,
        buf: &mut [i16; PDM_FRAME_SAMPLES],
        mut poll_fn: F,
    ) -> bool {
        if !self.is_running {
            pdm.enable.write(|w| w.enable().enabled());
            self.is_running = true;
        }

        pdm.sample
            .ptr
            .write(|w| unsafe { w.bits(buf.as_mut_ptr() as u32) });
        pdm.sample
            .maxcnt
            .write(|w| unsafe { w.buffsize().bits(PDM_FRAME_SAMPLES as u16) });

        pdm.events_started.write(|w| unsafe { w.bits(0) });
        pdm.events_end.write(|w| unsafe { w.bits(0) });
        pdm.events_stopped.write(|w| unsafe { w.bits(0) });

        cortex_m::asm::dsb();
        pdm.tasks_start.write(|w| unsafe { w.bits(1) });

        // 80 samples @ 16 kHz takes 5.0 ms; allow up to ~25 ms (~400,000 loops)
        let mut guard: u32 = 400_000;
        while pdm.events_end.read().bits() == 0 {
            poll_fn();
            guard -= 1;
            if guard == 0 {
                pdm.tasks_stop.write(|w| unsafe { w.bits(1) });
                return false;
            }
        }

        pdm.tasks_stop.write(|w| unsafe { w.bits(1) });
        let mut stop_guard: u32 = 50_000;
        while pdm.events_stopped.read().bits() == 0 && stop_guard > 0 {
            stop_guard -= 1;
        }
        cortex_m::asm::dsb();
        true
    }

    /// Capture a single 80-sample PCM frame without background polling.
    #[allow(dead_code)]
    pub fn capture_frame(&mut self, pdm: &PDM, buf: &mut [i16; PDM_FRAME_SAMPLES]) -> bool {
        self.capture_frame_with_poll(pdm, buf, || {})
    }

    /// Cleanly stop PDM peripheral before entering sleep (saves ~1.5 mA).
    pub fn sleep(&mut self, pdm: &PDM) {
        if self.is_running {
            pdm.tasks_stop.write(|w| unsafe { w.bits(1) });
            pdm.enable.write(|w| w.enable().disabled());
            self.is_running = false;
        }
    }

    /// Resume PDM peripheral after waking from sleep.
    pub fn wake(&mut self, pdm: &PDM) {
        if !self.is_running {
            pdm.enable.write(|w| w.enable().enabled());
            self.is_running = true;
        }
    }
}

/// LSM6DS3TR-C 6-Axis IMU I2C (`TWIM0`) Driver (`P1.08` `IMU_PWR`, `P0.27` `SCL`, `P0.07` `SDA`, `P0.11` `INT1`).
pub struct Lsm6ds3ImuDriver {
    pub addr: u8,
    pub who_am_i: u8,
}

impl Lsm6ds3ImuDriver {
    pub const PIN_IMU_PWR_P1: usize = 8; // P1.08
    pub const PIN_SCL_P0: usize = 27;    // P0.27
    pub const PIN_SDA_P0: usize = 7;     // P0.07
    pub const PIN_INT1_P0: usize = 11;   // P0.11

    pub const fn new() -> Self {
        Self {
            addr: LSM6DS3_ADDR_PRIMARY,
            who_am_i: 0,
        }
    }

    /// Power up `P1.08` (`IMU_PWR` with `H0H1` high drive), configure `TWIM0` at 400 kHz,
    /// verify `WHO_AM_I == 0x6A`, and start 416 Hz accelerometer + gyro.
    pub fn init_with_poll<F: FnMut()>(
        &mut self,
        p0: &P0,
        p1: &P1,
        twim0: &TWIM0,
        timer: &mut MonotonicTimer,
        timer0: &TIMER0,
        mut poll_fn: F,
    ) -> Result<u8, &'static str> {
        // 1. Enable P1.08 (IMU_PWR) with H0H1 high drive + 80 ms boot time
        p1.outset.write(|w| unsafe { w.bits(1 << Self::PIN_IMU_PWR_P1) });
        p1.pin_cnf[Self::PIN_IMU_PWR_P1].write(|w| {
            w.dir()
                .output()
                .input()
                .disconnect()
                .pull()
                .disabled()
                .drive()
                .h0h1()
        });
        timer.delay_ms_with_poll(timer0, 80, &mut poll_fn);

        // Configure INT1 (P0.11) as input
        p0.pin_cnf[Self::PIN_INT1_P0].write(|w| {
            w.dir()
                .input()
                .input()
                .connect()
                .pull()
                .pulldown()
                .drive()
                .s0s1()
        });

        // 2. Configure SCL (P0.27) and SDA (P0.07) with open-drain S0D1 + internal pullup
        for &pin in &[Self::PIN_SCL_P0, Self::PIN_SDA_P0] {
            p0.pin_cnf[pin].write(|w| {
                w.dir()
                    .input()
                    .input()
                    .connect()
                    .pull()
                    .pullup()
                    .drive()
                    .s0d1()
            });
        }

        twim0.enable.write(|w| w.enable().disabled());
        twim0.psel.scl.write(|w| unsafe {
            w.pin()
                .bits(Self::PIN_SCL_P0 as u8)
                .port()
                .bit(false)
                .connect()
                .connected()
        });
        twim0.psel.sda.write(|w| unsafe {
            w.pin()
                .bits(Self::PIN_SDA_P0 as u8)
                .port()
                .bit(false)
                .connect()
                .connected()
        });
        twim0.frequency.write(|w| w.frequency().k400());
        twim0.enable.write(|w| w.enable().enabled());

        // 3. Probe 0x6A (fallback 0x6B) for WHO_AM_I (0x0F) == 0x6A
        let mut found_who = 0u8;
        for &candidate in &[LSM6DS3_ADDR_PRIMARY, LSM6DS3_ADDR_ALT] {
            self.addr = candidate;
            if let Ok(val) = self.read_reg(twim0, REG_WHO_AM_I) {
                if val == WHO_AM_I_EXPECTED {
                    found_who = val;
                    break;
                }
            }
        }
        if found_who != WHO_AM_I_EXPECTED {
            return Err("LSM6DS3TR-C WHO_AM_I (0x6A) not found on internal I2C bus");
        }
        self.who_am_i = found_who;

        // 4. Configure CTRL3_C (0x44: BDU + IF_INC), CTRL1_XL (0x68: 416 Hz, +/-4g), CTRL2_G (0x60: 416 Hz, 250 dps)
        self.write_reg(twim0, REG_CTRL3_C, 0x44)?;
        self.write_reg(twim0, REG_CTRL1_XL, 0x68)?;
        self.write_reg(twim0, REG_CTRL2_G, 0x60)?;
        timer.delay_ms_with_poll(timer0, 20, &mut poll_fn);

        Ok(found_who)
    }

    pub fn write_reg(&self, twim0: &TWIM0, reg: u8, val: u8) -> Result<(), &'static str> {
        let tx_buf: [u8; 2] = [reg, val];
        twim0
            .address
            .write(|w| unsafe { w.address().bits(self.addr) });
        twim0
            .txd
            .ptr
            .write(|w| unsafe { w.bits(tx_buf.as_ptr() as u32) });
        twim0.txd.maxcnt.write(|w| unsafe { w.bits(2) });
        twim0.rxd.maxcnt.write(|w| unsafe { w.bits(0) });
        twim0.shorts.write(|w| w.lasttx_stop().enabled());

        twim0.events_stopped.write(|w| unsafe { w.bits(0) });
        twim0.events_error.write(|w| unsafe { w.bits(0) });
        cortex_m::asm::dsb();
        twim0.tasks_starttx.write(|w| unsafe { w.bits(1) });

        let mut guard: u32 = 100_000;
        while twim0.events_stopped.read().bits() == 0 {
            if twim0.events_error.read().bits() != 0 {
                twim0.events_error.write(|w| unsafe { w.bits(0) });
                twim0.tasks_stop.write(|w| unsafe { w.bits(1) });
                return Err("TWIM0 I2C write error");
            }
            guard -= 1;
            if guard == 0 {
                twim0.tasks_stop.write(|w| unsafe { w.bits(1) });
                return Err("TWIM0 I2C write timeout");
            }
        }
        twim0.shorts.reset();
        Ok(())
    }

    pub fn read_regs(&self, twim0: &TWIM0, start_reg: u8, rx_buf: &mut [u8]) -> Result<(), &'static str> {
        let tx_buf: [u8; 1] = [start_reg];
        twim0
            .address
            .write(|w| unsafe { w.address().bits(self.addr) });
        twim0
            .txd
            .ptr
            .write(|w| unsafe { w.bits(tx_buf.as_ptr() as u32) });
        twim0.txd.maxcnt.write(|w| unsafe { w.bits(1) });
        twim0
            .rxd
            .ptr
            .write(|w| unsafe { w.bits(rx_buf.as_mut_ptr() as u32) });
        twim0
            .rxd
            .maxcnt
            .write(|w| unsafe { w.bits(rx_buf.len() as u32) });
        twim0
            .shorts
            .write(|w| w.lasttx_startrx().enabled().lastrx_stop().enabled());

        twim0.events_stopped.write(|w| unsafe { w.bits(0) });
        twim0.events_error.write(|w| unsafe { w.bits(0) });
        cortex_m::asm::dsb();
        twim0.tasks_starttx.write(|w| unsafe { w.bits(1) });

        let mut guard: u32 = 150_000;
        while twim0.events_stopped.read().bits() == 0 {
            if twim0.events_error.read().bits() != 0 {
                twim0.events_error.write(|w| unsafe { w.bits(0) });
                twim0.tasks_stop.write(|w| unsafe { w.bits(1) });
                return Err("TWIM0 I2C read error");
            }
            guard -= 1;
            if guard == 0 {
                twim0.tasks_stop.write(|w| unsafe { w.bits(1) });
                return Err("TWIM0 I2C read timeout");
            }
        }
        twim0.shorts.reset();
        cortex_m::asm::dsb();
        Ok(())
    }

    pub fn read_reg(&self, twim0: &TWIM0, reg: u8) -> Result<u8, &'static str> {
        let mut buf = [0u8; 1];
        self.read_regs(twim0, reg, &mut buf)?;
        Ok(buf[0])
    }

    /// Read 3-axis accelerometer in `g` (`+/- 4g` scale: `0.122 mg/LSB`).
    pub fn read_accel_g(&self, twim0: &TWIM0) -> Result<(f32, f32, f32), &'static str> {
        let mut buf = [0u8; 6];
        self.read_regs(twim0, REG_OUTX_L_XL, &mut buf)?;
        let ax_raw = i16::from_le_bytes([buf[0], buf[1]]);
        let ay_raw = i16::from_le_bytes([buf[2], buf[3]]);
        let az_raw = i16::from_le_bytes([buf[4], buf[5]]);
        let scale = 0.000_122_f32;
        Ok((
            (ax_raw as f32) * scale,
            (ay_raw as f32) * scale,
            (az_raw as f32) * scale,
        ))
    }

    /// Read 3-axis gyroscope in `dps` (`250 dps` scale: `8.75 mdps/LSB`).
    pub fn read_gyro_dps(&self, twim0: &TWIM0) -> Result<(f32, f32, f32), &'static str> {
        let mut buf = [0u8; 6];
        self.read_regs(twim0, REG_OUTX_L_G, &mut buf)?;
        let gx_raw = i16::from_le_bytes([buf[0], buf[1]]);
        let gy_raw = i16::from_le_bytes([buf[2], buf[3]]);
        let gz_raw = i16::from_le_bytes([buf[4], buf[5]]);
        let scale = 0.008_75_f32;
        Ok((
            (gx_raw as f32) * scale,
            (gy_raw as f32) * scale,
            (gz_raw as f32) * scale,
        ))
    }

    /// Put LSM6DS3TR-C into 26 Hz low-power accelerometer wake mode (`CTRL2_G = 0x00`, `CTRL1_XL = 0x28`).
    pub fn enter_low_power(&self, twim0: &TWIM0) {
        let _ = self.write_reg(twim0, REG_CTRL2_G, 0x00);
        let _ = self.write_reg(twim0, REG_CTRL1_XL, 0x28);
        let _ = self.write_reg(twim0, REG_TAP_CFG, 0x90);
        let _ = self.write_reg(twim0, REG_WAKE_UP_DUR, 0x00);
        let _ = self.write_reg(twim0, REG_WAKE_UP_THS, 0x02);
        let _ = self.write_reg(twim0, REG_MD1_CFG, 0x20);
    }

    /// Restore 416 Hz active accelerometer + gyro mode on wake.
    pub fn restore_active(&self, twim0: &TWIM0) {
        let _ = self.write_reg(twim0, REG_MD1_CFG, 0x00);
        let _ = self.write_reg(twim0, REG_CTRL1_XL, 0x68);
        let _ = self.write_reg(twim0, REG_CTRL2_G, 0x60);
    }
}

/// Bare-Metal 2.4 GHz Bluetooth Low Energy (BLE 1 Mbps) Advertiser Driver (`NRF_RADIO`).
///
/// Transmits non-connectable undirected advertising (`ADV_NONCONN_IND`) packets across
/// primary BLE advertising channels 37 (2402 MHz), 38 (2426 MHz), and 39 (2480 MHz)
/// using EasyDMA, broadcasting BTHome v2 (`UUID 0xFCD2`) tempo frames for Android Sensor Logger.
pub struct BleRadioDriver {
    pub mac: [u8; 6],
    pub tx_count: u32,
}

impl BleRadioDriver {
    pub const fn new() -> Self {
        Self {
            mac: [0; 6],
            tx_count: 0,
        }
    }

    /// Initialize `NRF_RADIO` for BLE 1 Mbps advertising and read the factory device address from `FICR`.
    pub fn init(&mut self, radio: &RADIO, ficr: &FICR) {
        let addr0 = ficr.deviceaddr[0].read().bits();
        let addr1 = ficr.deviceaddr[1].read().bits();
        self.mac = format_random_static_mac(addr0, addr1);

        // Power on radio peripheral and configure for BLE 1Mbit
        radio.power.write(|w| w.power().enabled());
        radio.mode.write(|w| w.mode().ble_1mbit());
        // +4 dBm transmit power for strong indoor range to Android phones
        radio.txpower.write(|w| w.txpower().pos4d_bm());

        // BLE Advertising Access Address = 0x8E89BED6
        // With BALEN = 3 (3 base address bytes + 1 prefix byte):
        // BASE0 uses the upper 24 bits of the 32-bit register: 0x89BED600
        // PREFIX0.AP0 holds the MSB byte: 0x8E
        radio.base0.write(|w| unsafe { w.bits(0x89BE_D600) });
        radio.prefix0.write(|w| unsafe { w.ap0().bits(0x8E) });
        radio.txaddress.write(|w| unsafe { w.txaddress().bits(0) });

        // PCNF0: S0 = 1 byte, LENGTH = 8 bits, S1 = 0 bits, Preamble = 8-bit
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

        // PCNF1: MAXLEN = 37 bytes, STATLEN = 0, BALEN = 3, Little Endian, Data Whitening Enabled
        radio.pcnf1.write(|w| unsafe {
            w.maxlen()
                .bits(37)
                .statlen()
                .bits(0)
                .balen()
                .bits(3)
                .endian()
                .little()
                .whiteen()
                .enabled()
        });

        // 24-bit BLE CRC: 3 bytes, skip access address, polynomial 0x00065B, init 0x555555
        radio
            .crccnf
            .write(|w| w.len().three().skipaddr().skip());
        radio.crcpoly.write(|w| unsafe { w.crcpoly().bits(0x00065B) });
        radio.crcinit.write(|w| unsafe { w.crcinit().bits(0x555555) });

        // Fast ramp-up mode + hardware shortcuts: READY -> START and END -> DISABLE
        radio.modecnf0.write(|w| w.ru().fast().dtx().center());
        radio
            .shorts
            .write(|w| w.ready_start().enabled().end_disable().enabled());
    }

    /// Broadcast the current tempo (`bpm`) across BLE advertising channels 37, 38, and 39.
    /// Total transmit time across all 3 channels with fast ramp-up is ~950 microseconds.
    pub fn broadcast_tempo(&mut self, radio: &RADIO, bpm: f32) {
        let (pdu, _len): ([u8; MAX_BLE_PDU_LEN], usize) = build_tempo_adv_pdu(self.mac, bpm);

        radio
            .packetptr
            .write(|w| unsafe { w.bits(pdu.as_ptr() as u32) });

        for &(chan, freq_offset_mhz) in &BLE_ADV_CHANNELS {
            radio
                .frequency
                .write(|w| unsafe { w.frequency().bits(freq_offset_mhz) });
            radio
                .datawhiteiv
                .write(|w| unsafe { w.datawhiteiv().bits(chan) });

            radio.events_disabled.write(|w| unsafe { w.bits(0) });
            cortex_m::asm::dsb();
            radio.tasks_txen.write(|w| unsafe { w.bits(1) });

            // Wait for READY -> START -> END -> DISABLED (~300 us per channel)
            let mut guard: u32 = 40_000;
            while radio.events_disabled.read().bits() == 0 && guard > 0 {
                guard -= 1;
            }
            if guard == 0 {
                radio.tasks_disable.write(|w| unsafe { w.bits(1) });
                let mut stop_guard: u32 = 10_000;
                while radio.events_disabled.read().bits() == 0 && stop_guard > 0 {
                    stop_guard -= 1;
                }
            }
        }
        core::sync::atomic::compiler_fence(core::sync::atomic::Ordering::SeqCst);

        self.tx_count = self.tx_count.wrapping_add(1);
    }
}

