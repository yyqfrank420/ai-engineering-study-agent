# Message ordering migration

Migration `20260912_0007` gives every message a database-generated
`message_sequence`. Reads sort by this column before applying their existing
message-count limits. `get_history` returns the newest limited rows in ascending
sequence order; `get_messages` returns the oldest limited rows. An odd limit can
start or end inside a turn. The API does not promise complete turn pairs.

PostgreSQL uses a unique bigint identity with `CACHE 1 NO CYCLE`. SQLite uses an
`INTEGER PRIMARY KEY AUTOINCREMENT`; message UUIDs remain non-null and unique.
Writers omit the new column, including older application versions. Sequence gaps
are valid after rollback or deletion, and other threads can allocate intervening
values. Neither readers nor writers infer message counts or turn identity from
arithmetic on sequence values. `client_request_id` remains the idempotency key.

`persist_turn` serializes same-thread writes with a PostgreSQL thread-row lock or
SQLite `BEGIN IMMEDIATE`. Single-message `append` uses the same transaction and
lock pattern. The sequence records allocation order, not wall-clock time or
cross-thread commit order. Existing timestamps remain available for display and
for older readers during rollout.

## Existing messages

PostgreSQL timestamps do not determine the order of messages tied within a
transaction. Earlier chronology among multiple tied turns cannot be recovered
from the stored columns. The backfill orders by turn timestamp, thread, user, request
key, role, and UUID. A non-null request key keeps its user before its assistant;
their earliest timestamp orders the pair. Request-key and UUID tie-breakers are
deterministic, not evidence of original chronology. Legacy rows without request
keys cannot have their turn pairing recovered reliably.

SQLite retains a local insertion order in `rowid`. Its upgrade copies existing
rows in that order into the replacement table, preserving UUIDs, content,
timestamps, request keys, foreign keys, and the existing indexes. Table replacement
and index recreation run within one immediate transaction. A failed copy rolls
back without dropping the original data.

## PostgreSQL rollout and recovery

Before applying the migration, measure `chat_messages` row count and relation
size, test the backfill against a comparable disposable database, and review the
expected write interruption. The migration takes an access-exclusive table lock
with a five-second acquisition timeout and a sixty-second timeout per statement.
It installs the backfill, identity default, uniqueness, and reader index in one
transaction. Index creation shares this lock so old writers never see an interim
nullable column without its database default. A statement timeout or database
error rolls back the entire migration. Large tables that cannot fit these bounds
need a separately reviewed migration plan; do not raise the bounds blindly.

Apply the migration before deploying readers that require `message_sequence`.
The existing timestamp index remains installed. Older writers continue to receive
sequence values automatically after the migration commits. No application-side
allocation counter or trigger is required.

The staging migration identity owns its tables and generated identity sequence.
No grants to `anon`, `authenticated`, or broader application roles are added.
Verify an insert with the deployed restricted role using the existing column list
on a disposable staging database, along with existing RLS and cross-user checks.
If a deployment uses a different table writer, verify its identity insert
privileges independently before rollout.

Verify non-null, unique sequence values, `is_identity = YES`,
`identity_generation = ALWAYS`, `cache_size = 1`, and `cycle = false`; both
`uq_chat_messages_sequence` and `idx_chat_messages_thread_sequence` must exist.
Exercise two same-timestamp turns, a limited history read, an idempotent replay,
and an old-style insert that omits the sequence column.

Application rollback should retain this additive schema and its ordering data.
The migration downgrade drops the sequence column and its dependent indexes and
identity sequence. Run it only after all new readers are drained or reverted.
Downgrade loses the ordering fact; it is not data-restoration-safe without a
backup of message UUID-to-sequence mappings. Prefer forward recovery after a
successful migration.
