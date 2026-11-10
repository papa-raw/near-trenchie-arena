//! The hourly batch's row format, shared by `arena` (which stores the fight hash
//! and forwards the rows) and `trenchie_nft` (which applies them). Item-system §5.

use near_sdk::near;

/// One bag entry, 12 bytes in borsh: `row u16 · serial u16 · born_batch u32 ·
/// kos u16 · hands u8 · flags u8`. `row` points into the rules table, so stats,
/// look and name are never stored. `(row, serial)` names one copy of an item.
#[near(serializers = [borsh, json])]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Entry {
    pub row: u16,
    pub serial: u16,
    pub born_batch: u32,
    pub kos: u16,
    pub hands: u8,
    pub flags: u8,
}

impl Entry {
    pub fn key(&self) -> u32 {
        ((self.row as u32) << 16) | self.serial as u32
    }
}

/// A persona's record as it stands after the batch (absolute, so a row is
/// idempotent). `skill` is the prediction skill score in thousandths.
#[near(serializers = [borsh, json])]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub struct Record {
    pub lives: u32,
    pub kos: u32,
    pub skill: i32,
}

/// One row per persona touched in the batch: its bag as it stands, its record,
/// and, when it changes, the sale-ready flag.
#[near(serializers = [borsh, json])]
#[derive(Clone, Debug, PartialEq)]
pub struct Row {
    pub token_id: String,
    pub bag: Vec<Entry>,
    pub record: Record,
    pub sale_ready: Option<bool>,
}

/// A bag holds one of each row, at most this many entries.
pub const MAX_BAG: usize = 48;

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn entry_is_twelve_bytes() {
        let e = Entry { row: 7, serial: 1607, born_batch: 3, kos: 2, hands: 5, flags: 0 };
        assert_eq!(near_sdk::borsh::to_vec(&e).unwrap().len(), 12);
        assert_eq!(e.key(), (7 << 16) | 1607);
    }
}
