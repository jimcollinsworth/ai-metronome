//! Retained SRAM Crash / Panic Logger (`no_std`).
//!
//! Stores panic file, line number, and message in the top 256 bytes of SRAM
//! (`0x2003FF00..0x20040000`) which survives nRF52840 soft resets and watchdog resets.

pub const CRASH_MAGIC: u32 = 0xDEAD_C0DE;
pub const MAX_CRASH_MSG_LEN: usize = 180;

#[repr(C)]
#[derive(Clone, Copy)]
pub struct RetainedCrashLog {
    pub magic: u32,
    pub line: u32,
    pub msg_len: u16,
    pub msg: [u8; MAX_CRASH_MSG_LEN],
    pub checksum: u32,
}

impl RetainedCrashLog {
    pub const fn empty() -> Self {
        Self {
            magic: 0,
            line: 0,
            msg_len: 0,
            msg: [0u8; MAX_CRASH_MSG_LEN],
            checksum: 0,
        }
    }

    pub fn compute_checksum(&self) -> u32 {
        let mut hash: u32 = self.magic ^ self.line ^ (self.msg_len as u32);
        let len = (self.msg_len as usize).min(MAX_CRASH_MSG_LEN);
        for &b in &self.msg[..len] {
            hash = hash.rotate_left(5) ^ (b as u32);
        }
        hash
    }

    pub fn record(&mut self, file_and_reason: &[u8], line: u32) {
        self.magic = CRASH_MAGIC;
        self.line = line;
        let len = file_and_reason.len().min(MAX_CRASH_MSG_LEN);
        self.msg = [0u8; MAX_CRASH_MSG_LEN];
        self.msg[..len].copy_from_slice(&file_and_reason[..len]);
        self.msg_len = len as u16;
        self.checksum = self.compute_checksum();
    }

    pub fn is_valid(&self) -> bool {
        self.magic == CRASH_MAGIC
            && (self.msg_len as usize) <= MAX_CRASH_MSG_LEN
            && self.checksum == self.compute_checksum()
    }

    pub fn clear(&mut self) {
        self.magic = 0;
        self.line = 0;
        self.msg_len = 0;
        self.checksum = 0;
    }

    pub fn message_str(&self) -> &str {
        let len = (self.msg_len as usize).min(MAX_CRASH_MSG_LEN);
        core::str::from_utf8(&self.msg[..len]).unwrap_or("<invalid utf8>")
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_crash_log_record_validate_and_clear() {
        let mut log = RetainedCrashLog::empty();
        assert!(!log.is_valid());

        log.record(b"src/main.rs: PDM DMA timeout", 142);
        assert!(log.is_valid());
        assert_eq!(log.line, 142);
        assert_eq!(log.message_str(), "src/main.rs: PDM DMA timeout");

        log.clear();
        assert!(!log.is_valid());
    }
}
