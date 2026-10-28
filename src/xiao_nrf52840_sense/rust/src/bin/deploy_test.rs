//! Minimal USB Serial Print Test for Seeed Studio XIAO nRF52840 Sense.

#![no_std]
#![no_main]

use core::panic::PanicInfo;

use cortex_m_rt::{entry, exception};
use nrf52840_hal::clocks::Clocks;
use nrf52840_hal::pac::{self, NVIC, SCB};
use nrf52840_hal::usbd::{UsbPeripheral, Usbd};
use usb_device::class_prelude::UsbBusAllocator;
use usb_device::device::{StringDescriptors, UsbDeviceBuilder, UsbDeviceState, UsbVidPid};
use usbd_serial::{SerialPort, USB_CLASS_CDC};

const CLEAN_BOOT_FLAG_PTR: *mut u32 = 0x2003_FEFC as *mut u32;
const CLEAN_BOOT_MAGIC: u32 = 0xB007_C1EA;
const DFU_MAGIC_UF2_RESET: u32 = 0x57;

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

        // After UF2 flashing, the bootloader jumps here without a hardware reset,
        // leaving NRF_USBD dirty from TinyUSB. A single SCB::sys_reset() resets all
        // peripherals cleanly; the bootloader then skips TinyUSB and jumps right back!
        if core::ptr::read_volatile(CLEAN_BOOT_FLAG_PTR) != CLEAN_BOOT_MAGIC {
            core::ptr::write_volatile(CLEAN_BOOT_FLAG_PTR, CLEAN_BOOT_MAGIC);
            cortex_m::asm::delay(12_800_000);
            cortex_m::asm::dsb();
            SCB::sys_reset();
        }
        core::ptr::write_volatile(CLEAN_BOOT_FLAG_PTR, 0);
    }

    let dp = pac::Peripherals::take().unwrap();
    // Turn on Green LED (P0.30 active-low) immediately to confirm app entry
    dp.P0.pin_cnf[30].write(|w| w.dir().output());
    dp.P0.outclr.write(|w| w.pin30().clear());

    let clocks = Clocks::new(dp.CLOCK).enable_ext_hfosc();

    let usb_bus = UsbBusAllocator::new(Usbd::new(UsbPeripheral::new(dp.USBD, &clocks)));
    let mut serial = SerialPort::new(&usb_bus);
    let mut usb_dev = UsbDeviceBuilder::new(&usb_bus, UsbVidPid(0x2886, 0x0045))
        .strings(&[StringDescriptors::default()
            .manufacturer("Seeed Studio")
            .product("XIAO Rust Debug")
            .serial_number("XIAO-DBG")])
        .unwrap()
        .device_class(USB_CLASS_CDC)
        .max_packet_size_0(64)
        .unwrap()
        .build();

    let mut was_1200_armed = false;
    let mut tick: u32 = 0;
    let mut rx_buf = [0u8; 16];

    loop {
        let _ = usb_dev.poll(&mut [&mut serial]);

        if usb_dev.state() == UsbDeviceState::Configured {
            let rate = serial.line_coding().data_rate();
            let dtr = serial.dtr();
            if rate == 1200 {
                was_1200_armed = true;
            }
            if was_1200_armed && !dtr {
                dp.POWER.gpregret.write(|w| unsafe { w.bits(DFU_MAGIC_UF2_RESET) });
                cortex_m::asm::dsb();
                SCB::sys_reset();
            }

            if let Ok(count) = serial.read(&mut rx_buf) {
                for &b in &rx_buf[..count] {
                    if b == b'b' || b == b'B' {
                        dp.POWER.gpregret.write(|w| unsafe { w.bits(DFU_MAGIC_UF2_RESET) });
                        cortex_m::asm::dsb();
                        SCB::sys_reset();
                    }
                }
            }

            if dtr {
                tick = tick.wrapping_add(1);
                if tick % 80_000 == 1 {
                    let _ = serial.write(b"[DEPLOY_TEST] Hello from XIAO Rust!\r\n");
                }
            } else {
                tick = 0;
            }
        }
    }
}
