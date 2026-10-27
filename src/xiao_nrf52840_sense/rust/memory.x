/* Linker memory map for Seeed Studio XIAO nRF52840 Sense (Adafruit UF2 Bootloader, No SoftDevice)
 *
 * Flash Map:
 *   0x00000000 - 0x00001000 (  4 KB) : Nordic MBR (Master Boot Record)
 *   0x00001000 - 0x000ED000 (944 KB) : Application Firmware (linked at 0x00001000, VTOR=0x1000)
 *   0x000ED000 - 0x000F4000 ( 28 KB) : InternalFS reserved region
 *   0x000F4000 - 0x00100000 ( 48 KB) : Factory Adafruit UF2 Bootloader + Settings (DO NOT TOUCH)
 *
 * SRAM Map:
 *   0x20000000 - 0x20000008 (   8 B) : Reserved for MBR
 *   0x20000008 - 0x2003FF00 (255 KB) : Application RAM (.data, .bss, stack, heap)
 *   0x2003FF00 - 0x20040000 ( 256 B) : Retained Crash / Panic Log (.uninit)
 */
MEMORY
{
  FLASH : ORIGIN = 0x00001000, LENGTH = 944K
  RAM   : ORIGIN = 0x20000008, LENGTH = 262136
}
