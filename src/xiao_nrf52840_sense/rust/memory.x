/* Linker memory map for Seeed Studio XIAO nRF52840 Sense (Adafruit UF2 Bootloader + S140 v7.3.0)
 *
 * Flash Map:
 *   0x00000000 - 0x00001000 (  4 KB) : Nordic MBR (Master Boot Record)
 *   0x00001000 - 0x00027000 (152 KB) : Nordic SoftDevice S140 v7.3.0 (forwards reset to 0x00027000)
 *   0x00027000 - 0x000ED000 (792 KB) : Rust Application Firmware (linked at 0x00027000, VTOR=0x27000)
 *   0x000ED000 - 0x000F4000 ( 28 KB) : InternalFS reserved region
 *   0x000F4000 - 0x00100000 ( 48 KB) : Factory Adafruit UF2 Bootloader + Settings (DO NOT TOUCH)
 *
 * SRAM Map:
 *   0x20000000 - 0x20006000 (  24 KB) : Reserved for MBR & SoftDevice S140 v7.3.0
 *   0x20006000 - 0x2003FEF0 ( 231 KB) : Application RAM (.data, .bss, stack)
 *   0x2003FEF0 - 0x2003FF00 (  16 B ) : Clean-Boot Reset Trampoline Flag (CLEAN_BOOT_FLAG_PTR = 0x2003FEFC)
 *   0x2003FF00 - 0x20040000 ( 256 B ) : Retained Crash / Panic Log (CRASH_LOG_PTR = 0x2003FF00)
 */
MEMORY
{
  FLASH : ORIGIN = 0x00027000, LENGTH = 792K
  RAM   : ORIGIN = 0x20006000, LENGTH = 237296
}

_stack_start = ORIGIN(RAM) + LENGTH(RAM);


