// SPDX-License-Identifier: MIT
pragma solidity 0.8.24;

/// @title SABAGeo title registry (Polygon Amoy test network)
/// @notice One entry per land title: the fingerprint of its latest SABAGeo ledger record.
///         Anyone can read it; only the SABAGeo wallet that deployed it can write.
/// @dev titleId = keccak256(title code text), recordHash = the ledger record's SHA-256.
///      Writes are idempotent: an entry is only replaced by a NEWER ledger record, so sending
///      the same batch twice (for example after a crash) changes nothing and does not fail.
contract TitleRegistry {
    struct Title {
        bytes32 recordHash; // fingerprint of the latest ledger record for this title
        uint64 ledgerId;    // that record's number in the SABAGeo ledger
        uint64 updatedAt;   // block time of the write
        bool removed;       // true once the title was taken out of the registry
    }

    address public immutable owner;
    uint256 public titleCount;
    mapping(bytes32 => Title) private titles;

    event TitleRecorded(bytes32 indexed titleId, bytes32 recordHash, uint64 ledgerId);
    event TitleRemoved(bytes32 indexed titleId, bytes32 recordHash, uint64 ledgerId);

    error NotOwner();
    error LengthMismatch();
    error TooMany();

    constructor() {
        owner = msg.sender;
    }

    /// @notice Write a batch of titles. Entries older than (or the same as) what is stored are skipped.
    function write(
        bytes32[] calldata titleIds,
        bytes32[] calldata recordHashes,
        uint64[] calldata ledgerIds,
        bool[] calldata removed
    ) external {
        if (msg.sender != owner) revert NotOwner();
        uint256 n = titleIds.length;
        if (recordHashes.length != n || ledgerIds.length != n || removed.length != n) revert LengthMismatch();
        if (n > 100) revert TooMany();

        for (uint256 i = 0; i < n; i++) {
            Title storage t = titles[titleIds[i]];
            if (ledgerIds[i] <= t.ledgerId) continue; // already up to date: safe to resend
            if (t.ledgerId == 0) titleCount++;
            t.recordHash = recordHashes[i];
            t.ledgerId = ledgerIds[i];
            t.updatedAt = uint64(block.timestamp);
            t.removed = removed[i];
            if (removed[i]) emit TitleRemoved(titleIds[i], recordHashes[i], ledgerIds[i]);
            else emit TitleRecorded(titleIds[i], recordHashes[i], ledgerIds[i]);
        }
    }

    /// @notice Read one title. ledgerId 0 means the title has never been written.
    function get(bytes32 titleId)
        external
        view
        returns (bytes32 recordHash, uint64 ledgerId, uint64 updatedAt, bool removed)
    {
        Title storage t = titles[titleId];
        return (t.recordHash, t.ledgerId, t.updatedAt, t.removed);
    }
}
