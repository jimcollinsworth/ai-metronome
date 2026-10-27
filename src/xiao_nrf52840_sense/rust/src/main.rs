#![no_std]
#![no_main]

use core::fmt::{self, Write};
use core::panic::PanicInfo;

use cortex_m_rt::entry;
use nrf52840_hal::clocks::Clocks;
use nrf52840_hal::pac::{self, P0, P1, PDM, POWER, SAADC, SCB, TEMP, TIMER0, TWIM0, WDT};
use nrf52840_hal::usbd::{UsbPeripheral, Usbd};
use usb_device::class_prelude::UsbBusAllocator;
use usb_device::device::{StringDescriptors, UsbDevice, UsbDeviceBuilder, UsbVidPid};
use usbd_serial::{SerialPort, USB_CLASS_CDC};

use ai_metronome_rust::click_detector::ClickDetector;
use ai_metronome_rust::crash_log::RetainedCrashLog;
use ai_metronome_rust::gesture::{ShakeModeClassifier, SleepTransition, SleepWakeController};
use ai_metronome_rust::mode_engine::{LedColor, MetronomeMode, MetronomeModeEngine};

mod hardware;
use hardware::{
    feed_watchdog, init_watchdog, read_and_clear_reset_reason,
    read_power_diagnostics, reboot_to_uf2_bootloader, Lsm6ds3ImuDriver, MonotonicTimer,
    PdmMicDriver, RgbLedController, PDM_FRAME_SAMPLES,
};

/// Top 256 bytes of SRAM (`0x2003FF00`) reserved in `memory.x` for retained crash log across resets.
const CRASH_LOG_PTR: *mut RetainedCrashLog = 0x2003_FF00 as *mut RetainedCrashLog;

/// Fixed-capacity stack string buffer implementing `core::fmt::Write` for zero-heap USB formatting.
pub struct LineBuf<const N: usize> {
    buf: [u8; N],
    len: usize,
}

impl<const N: usize> LineBuf<N> {
    pub const fn new() -> Self {
        Self {
            buf: [0u8; N],
            len: 0,
        }
    }

    pub fn clear(&mut self) {
        self.len = 0;
    }

    pub fn as_bytes(&self) -> &[u8] {
        &self.buf[..self.len]
    }
}

impl<const N: usize> Write for LineBuf<N> {
    fn write_str(&mut self, s: &str) -> fmt::Result {
        let bytes = s.as_bytes();
        let avail = N.saturating_sub(self.len);
        let to_copy = bytes.len().min(avail);
        self.buf[self.len..self.len + to_copy].copy_from_slice(&bytes[..to_copy]);
        self.len += to_copy;
        Ok(())
    }
}

/// Custom bare-metal panic handler:
/// 1. Records panic file, line, and message into retained SRAM (`0x2003FF00`).
/// 2. Blinks an unmistakable Red/Blue SOS fault pattern on the XIAO RGB LED.
/// 3. Triggers a soft reset (`SCB::sys_reset()`) so the next boot reports `[CRASH_LOG]` over USB.
#[panic_handler]
fn panic(info: &PanicInfo) -> ! {
    let mut msg_buf = LineBuf::<180>::new();
    let mut line_num: u32 = 0;
    if let Some(loc) = info.location() {
        line_num = loc.line();
        let _ = write!(msg_buf, "{}:{}: {}", loc.file(), loc.line(), info);
    } else {
        let _ = write!(msg_buf, "{}", info);
    }

    unsafe {
        let crash_log = &mut *CRASH_LOG_PTR;
        crash_log.record(msg_buf.as_bytes(), line_num);

        // Blink fast alternating Red / Blue SOS pattern (~2.0s) before rebooting
        let p0 = &*P0::ptr();
        let mut led = RgbLedController::new();
        led.init(p0);
        for _ in 0..10 {
            led.set_color(p0, LedColor::Red);
            for _ in 0..800_000 {
                cortex_m::asm::nop();
            }
            led.set_color(p0, LedColor::Blue);
            for _ in 0..800_000 {
                cortex_m::asm::nop();
            }
        }
        led.off(p0);
    }

    SCB::sys_reset()
}

/// Poll USB CDC, check for 1200-baud bootloader touch, and read any incoming command byte.
fn poll_usb_and_read_cmd<'a>(
    usb_dev: &mut UsbDevice<'a, Usbd<UsbPeripheral<'a>>>,
    serial: &mut SerialPort<'a, Usbd<UsbPeripheral<'a>>>,
    power: &POWER,
    was_1200_armed: &mut bool,
) -> Option<u8> {
    if !usb_dev.poll(&mut [serial]) {
        return None;
    }

    let rate = serial.line_coding().data_rate();
    let dtr = serial.dtr();
    if rate == 1200 {
        *was_1200_armed = true;
    }
    if *was_1200_armed && !dtr {
        // Host touched port at 1200 baud and dropped DTR -> enter XIAO-SENSE UF2 bootloader!
        reboot_to_uf2_bootloader(power);
    }
    if rate != 1200 && dtr {
        *was_1200_armed = false;
    }

    let mut rx_buf = [0u8; 16];
    if let Ok(count) = serial.read(&mut rx_buf) {
        if count > 0 {
            // Return the last meaningful command byte in the packet
            for &b in rx_buf[..count].iter().rev() {
                if b != b'\r' && b != b'\n' && b != 0x03 {
                    return Some(b);
                }
            }
        }
    }
    None
}

/// Write a line over USB CDC Serial (non-blocking if host terminal is not connected).
fn usb_send_bytes<'a>(
    usb_dev: &mut UsbDevice<'a, Usbd<UsbPeripheral<'a>>>,
    serial: &mut SerialPort<'a, Usbd<UsbPeripheral<'a>>>,
    timer: &mut MonotonicTimer,
    timer0: &TIMER0,
    data: &[u8],
) {
    let _ = usb_dev.poll(&mut [serial]);
    if !serial.dtr() {
        // Still attempt a single non-blocking write into the USB endpoint FIFO
        let _ = serial.write(data);
        let _ = usb_dev.poll(&mut [serial]);
        return;
    }

    let mut offset = 0;
    let start_us = timer.now_us(timer0);
    while offset < data.len() {
        let _ = usb_dev.poll(&mut [serial]);
        match serial.write(&data[offset..]) {
            Ok(written) if written > 0 => {
                offset += written;
            }
            _ => {}
        }
        // Never block more than 25 ms per line if host stops draining USB CDC
        if timer.now_us(timer0).wrapping_sub(start_us) > 25_000 {
            break;
        }
    }
    let _ = usb_dev.poll(&mut [serial]);
}

#[allow(clippy::too_many_arguments)]
fn run_and_print_self_test<'a>(
    usb_dev: &mut UsbDevice<'a, Usbd<UsbPeripheral<'a>>>,
    serial: &mut SerialPort<'a, Usbd<UsbPeripheral<'a>>>,
    p0: &P0,
    p1: &P1,
    saadc: &SAADC,
    temp: &TEMP,
    pdm: &PDM,
    twim0: &TWIM0,
    wdt: &WDT,
    timer: &mut MonotonicTimer,
    timer0: &TIMER0,
    led: &mut RgbLedController,
    mic: &mut PdmMicDriver,
    imu: &mut Lsm6ds3ImuDriver,
    click_detector: &mut ClickDetector,
    mode_engine: &MetronomeModeEngine,
    reset_reason: &str,
) {
    let mut line = LineBuf::<192>::new();

    // Blue LED ON during initialization / self-test
    led.set_color(p0, LedColor::Blue);
    feed_watchdog(wdt);

    // Header
    line.clear();
    let _ = writeln!(
        line,
        "\r\n============================================================"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    line.clear();
    let _ = writeln!(
        line,
        "  XIAO nRF52840 Sense -- AI Metronome v2.6 (Rust Firmware)"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    line.clear();
    let _ = writeln!(
        line,
        "============================================================"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    // Check retained SRAM crash log from previous boot
    unsafe {
        let crash_log = &mut *CRASH_LOG_PTR;
        if crash_log.is_valid() {
            line.clear();
            let _ = writeln!(
                line,
                "[CRASH_LOG] Previous boot panicked (line {}): {}",
                crash_log.line,
                crash_log.message_str()
            );
            usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());
            crash_log.clear();
        }
    }

    // 1. Power & System Diagnostics ([DIAG])
    let pwr = read_power_diagnostics(p0, saadc, temp, timer, timer0);
    line.clear();
    let _ = writeln!(
        line,
        "  [DIAG] Battery Rail     : {:.2} V (~{}%) | {}",
        pwr.v_batt,
        pwr.batt_pct,
        if pwr.is_charging {
            "CHARGING (or Full)"
        } else {
            "NOT CHARGING"
        }
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    line.clear();
    let _ = writeln!(
        line,
        "  [DIAG] CPU Thermal      : {:.1} C | Reset: {}",
        pwr.die_temp_c, reset_reason
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    line.clear();
    let _ = writeln!(
        line,
        "  [DIAG] Memory / Storage : 240.0 KB RAM | 944.0 KB Flash"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    // 2. PDM Microphone Init & DMA Check ([MIC])
    feed_watchdog(wdt);
    mic.init(p0, p1, pdm, timer, timer0);
    line.clear();
    let _ = writeln!(
        line,
        "  [MIC]  Power Gate       : Active (P1.10 MIC_PWR = HIGH)"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    let mut audio_buf = [0i16; PDM_FRAME_SAMPLES];
    // Discard 2 warmup frames for DC filter settling
    let _ = mic.capture_frame(pdm, &mut audio_buf);
    let _ = mic.capture_frame(pdm, &mut audio_buf);
    let dma_ok = mic.capture_frame(pdm, &mut audio_buf);

    let mut s_min: i16 = i16::MAX;
    let mut s_max: i16 = i16::MIN;
    for &s in &audio_buf {
        if s < s_min {
            s_min = s;
        }
        if s > s_max {
            s_max = s;
        }
    }
    let p2p = (s_max as i32) - (s_min as i32);

    line.clear();
    if dma_ok && p2p > 0 {
        let _ = writeln!(
            line,
            "  [MIC]  Signal Health    : OK (16kHz 16-bit DMA, min={}, max={}, span={})",
            s_min, s_max, p2p
        );
    } else {
        let _ = writeln!(
            line,
            "  [FAIL] PDM Microphone stream stalled (dma_ok={}, span={})",
            dma_ok, p2p
        );
    }
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    // 3. IMU Init & Self-Test ([IMU])
    feed_watchdog(wdt);
    match imu.init(p0, p1, twim0, timer, timer0) {
        Ok(who) => {
            line.clear();
            let _ = writeln!(
                line,
                "  [IMU]  I2C Bus          : Operational (P0.27 SCL, P0.07 SDA @ 400kHz, addr=0x{:02x})",
                imu.addr
            );
            usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

            if let Ok((ax, ay, az)) = imu.read_accel_g(twim0) {
                line.clear();
                let _ = writeln!(
                    line,
                    "  [IMU]  Accelerometer    : Active (LSM6DS3TR-C WHO_AM_I=0x{:02X}, X={:+.2}g, Y={:+.2}g, Z={:+.2}g)",
                    who, ax, ay, az
                );
                usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());
            }
            if let Ok((gx, gy, gz)) = imu.read_gyro_dps(twim0) {
                line.clear();
                let _ = writeln!(
                    line,
                    "  [IMU]  Gyroscope        : Active (X={:+.2}dps, Y={:+.2}dps, Z={:+.2}dps)",
                    gx, gy, gz
                );
                usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());
            }
        }
        Err(err) => {
            line.clear();
            let _ = writeln!(line, "  [FAIL] IMU initialization failed: {}", err);
            usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());
        }
    }

    // 4. Ambient Noise Calibration ([CAL] - 25 frames, outlier-resistant lower tertile)
    feed_watchdog(wdt);
    line.clear();
    let _ = writeln!(
        line,
        "[CAL] Calibrating ambient high-frequency noise floor (25 frames)..."
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    let mut cal_peaks = [0i32; 25];
    for i in 0..25 {
        let _ = mic.capture_frame(pdm, &mut audio_buf);
        let (hp_peak, _, _, _) = ClickDetector::compute_hp_stats(&audio_buf);
        cal_peaks[i] = hp_peak;
        let _ = usb_dev.poll(&mut [serial]);
    }
    let floor = click_detector.calibrate_from_peaks(&cal_peaks);
    let trig_thresh = click_detector.current_threshold();

    line.clear();
    let _ = writeln!(
        line,
        "[CAL] Ambient HP Noise Floor Peak: {:.1} -> Trigger Threshold: {:.0}",
        floor, trig_thresh
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    // 5. Signal Ready (3 Green LED Blinks + [READY] Banner)
    feed_watchdog(wdt);
    led.signal_init_ok(p0, timer, timer0);

    line.clear();
    let _ = writeln!(
        line,
        "[READY] Initialization OK! (Green LED blinked 3x)"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    line.clear();
    let _ = writeln!(
        line,
        "[MODE] Active Mode: {} (Reset always starts in Mode 1)",
        mode_engine.mode.name()
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());

    line.clear();
    let _ = writeln!(
        line,
        "[DEBUG] Serial Keys: '1'..'4'=Mode, 'd'=Dump State, 'r'=Self-Test, 'z'=Sleep, 'b'=Bootloader\r\n"
    );
    usb_send_bytes(usb_dev, serial, timer, timer0, line.as_bytes());
}

#[entry]
fn main() -> ! {
    // 1. Ensure Cortex-M4F Vector Table Offset Register points to our application flash origin (0x00001000)
    unsafe {
        (*SCB::PTR).vtor.write(0x0000_1000);
    }

    let dp = pac::Peripherals::take().unwrap();

    // 2. Initialize Active-Low RGB LED FIRST so Blue turns ON immediately upon entry!
    let mut led = RgbLedController::new();
    led.init(&dp.P0);
    led.set_color(&dp.P0, LedColor::Blue);

    // 3. Inspect reset reason and start 5.0-second hardware watchdog (paused during WFI sleep)
    let reset_reason = read_and_clear_reset_reason(&dp.POWER);
    init_watchdog(&dp.WDT);

    // 4. Safely initialize Clocks without blocking indefinitely if oscillators were pre-started by bootloader
    if dp.CLOCK.hfclkstat.read().state().is_not_running() {
        dp.CLOCK.tasks_hfclkstart.write(|w| unsafe { w.bits(1) });
        let mut timeout = 2_000_000;
        while dp.CLOCK.events_hfclkstarted.read().bits() == 0 && timeout > 0 {
            timeout -= 1;
        }
    }
    dp.CLOCK.events_hfclkstarted.write(|w| unsafe { w.bits(1) });

    if dp.CLOCK.lfclkstat.read().state().is_not_running() {
        dp.CLOCK.lfclksrc.write(|w| w.src().rc());
        dp.CLOCK.tasks_lfclkstart.write(|w| unsafe { w.bits(1) });
        let mut timeout = 2_000_000;
        while dp.CLOCK.events_lfclkstarted.read().bits() == 0 && timeout > 0 {
            timeout -= 1;
        }
    }
    dp.CLOCK.events_lfclkstarted.write(|w| unsafe { w.bits(1) });

    let clocks = Clocks::new(dp.CLOCK)
        .enable_ext_hfosc()
        .start_lfclk();

    let mut timer = MonotonicTimer::new();
    timer.init(&dp.TIMER0);

    // 5. Wait for USB 3.3V power supply regulator if VBUS is connected
    let mut reg_guard = 500_000;
    while dp.POWER.usbregstatus.read().vbusdetect().is_vbus_present()
        && !dp.POWER.usbregstatus.read().outputrdy().is_ready()
        && reg_guard > 0
    {
        reg_guard -= 1;
    }

    // 6. Initialize Native USB CDC Serial (Seeed VID 0x2886, PID 0x0045)
    let usb_bus = UsbBusAllocator::new(Usbd::new(UsbPeripheral::new(dp.USBD, &clocks)));
    let mut serial = SerialPort::new(&usb_bus);
    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x2886, 0x0045))
        .strings(&[StringDescriptors::default()
            .manufacturer("Seeed Studio")
            .product("XIAO nRF52840 Sense AI Metronome (Rust)")
            .serial_number("XIAO-RUST-26")])
        .unwrap()
        .device_class(USB_CLASS_CDC)
        .max_packet_size_0(64)
        .unwrap()
        .build();

    // Poll USB for ~600 ms so Windows enumerates COM9 before startup self-test runs
    let boot_start_us = timer.now_us(&dp.TIMER0);
    let mut was_1200_armed = false;
    while timer.now_us(&dp.TIMER0).wrapping_sub(boot_start_us) < 600_000 {
        let _ = poll_usb_and_read_cmd(&mut usb_dev, &mut serial, &dp.POWER, &mut was_1200_armed);
        feed_watchdog(&dp.WDT);
    }

    // 6. Initialize Drivers & Core DSP / PLL / Gesture / Sleep State Machines
    let mut mic = PdmMicDriver::new();
    let mut imu = Lsm6ds3ImuDriver::new();
    let mut click_detector = ClickDetector::new();
    let mut mode_engine = MetronomeModeEngine::new(); // Always starts in Mode 1 (ON_BEAT, Red)
    let mut shake_classifier = ShakeModeClassifier::new();
    let mut sleep_controller = SleepWakeController::new();

    // Run full hardware self-test & calibration
    run_and_print_self_test(
        &mut usb_dev,
        &mut serial,
        &dp.P0,
        &dp.P1,
        &dp.SAADC,
        &dp.TEMP,
        &dp.PDM,
        &dp.TWIM0,
        &dp.WDT,
        &mut timer,
        &dp.TIMER0,
        &mut led,
        &mut mic,
        &mut imu,
        &mut click_detector,
        &mode_engine,
        reset_reason,
    );

    let init_now_sec = timer.now_sec(&dp.TIMER0);
    sleep_controller.notify_activity(init_now_sec);

    let mut audio_buf = [0i16; PDM_FRAME_SAMPLES];
    let mut last_imu_poll_sec = init_now_sec;
    let mut last_dtr = serial.dtr();
    let mut dtr_banner_replayed = false;
    let mut last_accel = (0.0f32, 0.0f32, 1.0f32);
    let mut last_dyn_g = 0.0f32;
    let mut last_jerk_g = 0.0f32;
    let mut frame_counter: u32 = 0;
    let mut line = LineBuf::<192>::new();

    // 7. Real-Time 200 Hz (5 ms PDM DMA frame) Main Loop
    loop {
        feed_watchdog(&dp.WDT);

        // Check if host terminal newly opened COM port within first 15s (auto-replay self-test once)
        let curr_dtr = serial.dtr();
        if curr_dtr && !last_dtr && !dtr_banner_replayed && timer.now_sec(&dp.TIMER0) < 15.0 {
            dtr_banner_replayed = true;
            // Small 80ms pause for host terminal to finish opening port
            let wait_start = timer.now_us(&dp.TIMER0);
            while timer.now_us(&dp.TIMER0).wrapping_sub(wait_start) < 80_000 {
                let _ = poll_usb_and_read_cmd(
                    &mut usb_dev,
                    &mut serial,
                    &dp.POWER,
                    &mut was_1200_armed,
                );
            }
            run_and_print_self_test(
                &mut usb_dev,
                &mut serial,
                &dp.P0,
                &dp.P1,
                &dp.SAADC,
                &dp.TEMP,
                &dp.PDM,
                &dp.TWIM0,
                &dp.WDT,
                &mut timer,
                &dp.TIMER0,
                &mut led,
                &mut mic,
                &mut imu,
                &mut click_detector,
                &mode_engine,
                reset_reason,
            );
            sleep_controller.notify_activity(timer.now_sec(&dp.TIMER0));
        }
        last_dtr = curr_dtr;

        // A. Capture 80-sample (5 ms @ 16 kHz) PDM frame via EasyDMA
        let _ = mic.capture_frame(&dp.PDM, &mut audio_buf);
        frame_counter = frame_counter.wrapping_add(1);
        let now_sec = timer.now_sec(&dp.TIMER0);

        // Turn off LED if pulse duration has elapsed
        led.poll(&dp.P0, now_sec);

        // B. Process audio frame through high-pass click detector
        let click_ev = click_detector.process_frame(&audio_buf, now_sec);
        if click_ev.is_click {
            if let Some(flash) = mode_engine.register_click(click_ev.onset_time_sec) {
                led.start_flash(&dp.P0, flash.color, flash.brightness, now_sec);
                line.clear();
                let _ = writeln!(
                    line,
                    "[CLICK #{:03}] HP_Peak={:4} Thresh={:3.0} Crest={:4.1} -> {} (Beat {}, {:.1} BPM, Locked={})",
                    click_detector.click_count,
                    click_ev.hp_peak,
                    click_ev.threshold,
                    click_ev.crest_factor,
                    flash.color.as_str(),
                    flash.beat_in_bar,
                    flash.bpm,
                    flash.is_locked
                );
                usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());
            } else {
                line.clear();
                let _ = writeln!(
                    line,
                    "[CLICK #{:03}] HP_Peak={:4} Thresh={:3.0} Crest={:4.1} -> (PLL Sync / Mode 2 Upbeat Armed, {:.1} BPM)",
                    click_detector.click_count,
                    click_ev.hp_peak,
                    click_ev.threshold,
                    click_ev.crest_factor,
                    mode_engine.bpm()
                );
                usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());
            }

            if mode_engine.is_locked {
                sleep_controller.notify_activity(now_sec);
            }
        }

        // C. Poll autonomous PLL beat / upbeat scheduler
        let now_pll_sec = timer.now_sec(&dp.TIMER0);
        if let Some(sched_flash) = mode_engine.poll(now_pll_sec) {
            led.start_flash(&dp.P0, sched_flash.color, sched_flash.brightness, now_pll_sec);
            let tag = if sched_flash.is_upbeat {
                "UPBEAT"
            } else {
                "PLL_BEAT"
            };
            line.clear();
            let _ = writeln!(
                line,
                "[{}] {} (Beat {}, {:.1} BPM, Locked={})",
                tag,
                sched_flash.color.as_str(),
                sched_flash.beat_in_bar,
                sched_flash.bpm,
                sched_flash.is_locked
            );
            usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());
        }

        // D. Poll USB Serial for debug & HIL commands
        let mut force_sleep = false;
        if let Some(cmd) =
            poll_usb_and_read_cmd(&mut usb_dev, &mut serial, &dp.POWER, &mut was_1200_armed)
        {
            match cmd {
                b'1' | b'2' | b'3' | b'4' => {
                    let target_mode = MetronomeMode::from_u8(cmd - b'0');
                    mode_engine.set_mode(target_mode);
                    sleep_controller.notify_activity(now_sec);
                    line.clear();
                    let _ = writeln!(
                        line,
                        "[SERIAL] Switched to Mode {}: {}",
                        target_mode as u8,
                        target_mode.name()
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());
                    led.signal_mode_change(
                        &dp.P0,
                        &mut timer,
                        &dp.TIMER0,
                        target_mode as u8,
                        target_mode.confirm_color(),
                    );
                }
                b'z' | b'Z' => {
                    force_sleep = true;
                }
                b'r' | b'R' | 0x04 => {
                    // 'r' or Ctrl-D (0x04 from xiao-cli hil-test): replay full hardware self-test
                    run_and_print_self_test(
                        &mut usb_dev,
                        &mut serial,
                        &dp.P0,
                        &dp.P1,
                        &dp.SAADC,
                        &dp.TEMP,
                        &dp.PDM,
                        &dp.TWIM0,
                        &dp.WDT,
                        &mut timer,
                        &dp.TIMER0,
                        &mut led,
                        &mut mic,
                        &mut imu,
                        &mut click_detector,
                        &mode_engine,
                        reset_reason,
                    );
                    sleep_controller.notify_activity(timer.now_sec(&dp.TIMER0));
                }
                b'd' | b'D' => {
                    let pwr = read_power_diagnostics(
                        &dp.P0,
                        &dp.SAADC,
                        &dp.TEMP,
                        &mut timer,
                        &dp.TIMER0,
                    );
                    line.clear();
                    let _ = writeln!(
                        line,
                        "\r\n--- [DEBUG STATE DUMP @ {:.2}s (Frame #{})] ---",
                        now_sec, frame_counter
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());

                    line.clear();
                    let _ = writeln!(
                        line,
                        "  DSP  : Floor={:.1}, Thresh={:.0}, PrevQuiet={:.1}, Clicks={}",
                        click_detector.noise_floor_peak,
                        click_detector.current_threshold(),
                        click_detector.prev_quiet_peak,
                        click_detector.click_count
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());

                    line.clear();
                    let _ = writeln!(
                        line,
                        "  PLL  : Mode={}, Locked={}, BPM={:.1}, BeatIdx={}",
                        mode_engine.mode.name(),
                        mode_engine.is_locked,
                        mode_engine.bpm(),
                        mode_engine.beat_index
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());

                    line.clear();
                    let _ = writeln!(
                        line,
                        "  IMU  : Accel=({:+.2},{:+.2},{:+.2})g, Dyn={:.3}g, Jerk={:.3}g, Idle={:.1}s/30s",
                        last_accel.0,
                        last_accel.1,
                        last_accel.2,
                        last_dyn_g,
                        last_jerk_g,
                        sleep_controller.idle_duration_sec(now_sec)
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());

                    line.clear();
                    let _ = writeln!(
                        line,
                        "  PWR  : VBatt={:.2}V ({}%), Charging={}, Temp={:.1}C\r\n",
                        pwr.v_batt, pwr.batt_pct, pwr.is_charging, pwr.die_temp_c
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());
                }
                b'b' | b'B' => {
                    line.clear();
                    let _ = writeln!(line, "[BOOTLOADER] Entering XIAO-SENSE UF2 Bootloader...");
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());
                    timer.delay_ms(&dp.TIMER0, 50);
                    reboot_to_uf2_bootloader(&dp.POWER);
                }
                _ => {}
            }
        }

        // E. Poll IMU at 50 Hz (every 20 ms) for Dual-Gesture Mode Switch & 30s Inactivity Sleep
        if (now_sec - last_imu_poll_sec) >= 0.020 || force_sleep {
            last_imu_poll_sec = now_sec;
            if let Ok((ax, ay, az)) = imu.read_accel_g(&dp.TWIM0) {
                last_accel = (ax, ay, az);
                let imu_res = shake_classifier.update(ax, ay, az, now_sec);
                last_dyn_g = imu_res.dyn_g;
                last_jerk_g = imu_res.jerk_g;

                if let Some(gesture) = imu_res.gesture {
                    let new_mode = mode_engine.cycle_mode();
                    sleep_controller.notify_activity(now_sec);

                    line.clear();
                    let _ = writeln!(
                        line,
                        "[GESTURE: {}] Mode -> {}: {} (Confirming: White Burst + {}x {})",
                        gesture.as_str(),
                        new_mode as u8,
                        new_mode.name(),
                        new_mode as u8,
                        new_mode.confirm_color().as_str()
                    );
                    usb_send_bytes(&mut usb_dev, &mut serial, &mut timer, &dp.TIMER0, line.as_bytes());

                    led.signal_mode_change(
                        &dp.P0,
                        &mut timer,
                        &dp.TIMER0,
                        new_mode as u8,
                        new_mode.confirm_color(),
                    );
                } else {
                    if mode_engine.is_locked {
                        sleep_controller.notify_activity(now_sec);
                    }
                    let trans =
                        sleep_controller.update_motion(imu_res.dyn_g, imu_res.jerk_g, now_sec);
                    if trans == SleepTransition::EnterSleep || force_sleep {
                        sleep_controller.is_sleeping = true;

                        line.clear();
                        let _ = writeln!(
                            line,
                            "[SLEEP] No movement for {:.0}s -> Fading Blue LED & entering low-power sleep until movement...",
                            sleep_controller.inactivity_timeout_sec
                        );
                        usb_send_bytes(
                            &mut usb_dev,
                            &mut serial,
                            &mut timer,
                            &dp.TIMER0,
                            line.as_bytes(),
                        );

                        // 1. Fade Blue LED down smoothly, stop PDM DMA, and put IMU in 26 Hz low-power mode
                        led.fade_blue_to_sleep(&dp.P0, &mut timer, &dp.TIMER0);
                        mic.sleep(&dp.PDM);
                        imu.enter_low_power(&dp.TWIM0);

                        // 2. Low-power 20 Hz motion wake loop
                        let mut prev_mag = 1.0f32;
                        loop {
                            feed_watchdog(&dp.WDT);
                            // Poll USB so 1200-baud bootloader reset or wake key works even while asleep
                            if let Some(wake_cmd) = poll_usb_and_read_cmd(
                                &mut usb_dev,
                                &mut serial,
                                &dp.POWER,
                                &mut was_1200_armed,
                            ) {
                                if wake_cmd == b'b' || wake_cmd == b'B' {
                                    reboot_to_uf2_bootloader(&dp.POWER);
                                }
                                break;
                            }

                            if let Ok((sx, sy, sz)) = imu.read_accel_g(&dp.TWIM0) {
                                let mag = libm::sqrtf(sx * sx + sy * sy + sz * sz);
                                let s_dyn = libm::fabsf(mag - 1.0);
                                let s_jerk = libm::fabsf(mag - prev_mag);
                                prev_mag = mag;

                                let w_now = timer.now_sec(&dp.TIMER0);
                                if sleep_controller.update_motion(s_dyn, s_jerk, w_now)
                                    == SleepTransition::WakeUp
                                {
                                    break;
                                }
                            }

                            // Wait 50 ms (20 Hz) while servicing USB
                            let sleep_step_us = timer.now_us(&dp.TIMER0);
                            while timer.now_us(&dp.TIMER0).wrapping_sub(sleep_step_us) < 50_000 {
                                let _ = poll_usb_and_read_cmd(
                                    &mut usb_dev,
                                    &mut serial,
                                    &dp.POWER,
                                    &mut was_1200_armed,
                                );
                                timer.delay_us(&dp.TIMER0, 2_000);
                            }
                        }

                        // 3. Restore 416 Hz IMU + 16 kHz PDM DMA and blink Green 2x on wake
                        imu.restore_active(&dp.TWIM0);
                        mic.wake(&dp.PDM);
                        led.signal_wake(&dp.P0, &mut timer, &dp.TIMER0);

                        let wake_sec = timer.now_sec(&dp.TIMER0);
                        sleep_controller.is_sleeping = false;
                        sleep_controller.notify_activity(wake_sec);
                        shake_classifier.reset_after_wake(wake_sec);
                        last_imu_poll_sec = wake_sec;

                        line.clear();
                        let _ = writeln!(
                            line,
                            "[WAKE] Movement detected -> CPU & PDM Mic resumed (Mode: {})",
                            mode_engine.mode.name()
                        );
                        usb_send_bytes(
                            &mut usb_dev,
                            &mut serial,
                            &mut timer,
                            &dp.TIMER0,
                            line.as_bytes(),
                        );
                    }
                }
            }
        }
    }
}
