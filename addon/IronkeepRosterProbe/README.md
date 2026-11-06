# Ironkeep Roster Probe

Development-only. This folder is not part of the Ironkeep addon. It does not read or write `IronkeepDB`, and it does not invite, remove, promote, or edit the guild. Delete the folder when the check is finished.

The first Forever test showed `GuildRoster` is nil and `GetGuildRosterInfo` returns rows. The old probe stopped at 200 rows because of its own cap. This version examines up to 500 indexes and says when that cap, an API error, or a changing member count makes the scan partial.

Field positions are not hardcoded. A match against `UnitName`, `UnitFullName`, `UnitClass`, `UnitLevel`, `UnitGUID`, or `GetGuildInfo` is reported as a match for your character only.

## Update an existing install

1. Replace `Interface\AddOns\IronkeepRosterProbe` with this folder. Do not change `Interface\AddOns\Ironkeep`.
2. `/reload`, or log in again.
3. The chat line `Ironkeep probe 0.0.2 loaded` means this version started. The interface version is `16001`.

A new install uses the same folder under the Forever client directory (`World of Warcraft\_forever_`). Enable **Ironkeep Roster Probe** on the character list. It has no dependency on Ironkeep.

## Commands

- `/ikprobe` — short overview. Also runs once after you enter the world.
- `/ikprobe fields` — one line per return position: types, nil counts, boolean totals, numeric range, string length, and whether your own row matches a unit or guild value.
- `/ikprobe identity` — which positions matched your name and character id, plus missing and duplicate counts. The values themselves are not printed.
- `/ikprobe events` — `GUILD_ROSTER_UPDATE` registration, the count since login, the count since the previous overview or events command, and the argument types.

`GuildRoster()` is never called. Nothing is saved.

## In-game procedure

Use the same Herberg character as the first test.

1. `/reload` and read the overview.
2. Confirm the scan line says `Scan: complete` and `Examined 214` (or whatever `GetNumGuildMembers` #1 is). If it says `partial`, stop and keep that line.
3. Run `/ikprobe fields`. Note which positions match your name, rank, class file token, level, and character id, and which boolean totals equal count #1 and count #2.
4. Run `/ikprobe identity`. Note missing and duplicate name and id counts.
5. Run `/ikprobe events` and write down both event counts.
6. Open the guild window. Do not invite, kick, promote, or edit a note.
7. Run `/ikprobe events` again. The “since the previous probe command” count is the events received while the window was opened.
8. Run `/ikprobe` once more. Compare count #2 with the guild window’s online number, and compare a candidate boolean with one member you know is offline.
9. Disable or delete `IronkeepRosterProbe` when finished.

## What a useful overview contains

- `GuildRoster = nil` and `GetGuildRosterInfo = function` on this client.
- `GetNumGuildMembers #1=214 #2=110` if the guild window still shows those numbers. The probe does not treat #2 as a confirmed online count.
- `Scan: complete` only when every reported index was read, the count stayed the same, and no roster call failed. A safety cap of 500 is stated on every scan line.
- `Online candidate` only when a boolean’s true/false split equals the two counts exactly. The next line says the mapping remains unverified.
- Last-online values for your row and for one row whose candidate boolean is false. Four nils are reported as nils. That reading does not mean the function is missing.
- No character names, notes, zones, or character ids from the roster. Guild-info strings of 40 characters or fewer are shown, except when one of them is your own name or id.

## Still needs this client

- Whether the same positions still match name, rank, class file, and character id after a full 214-row scan.
- Which boolean, if any, stays equal to the guild window’s online count on a second `/ikprobe`.
- Whether a row with that boolean false is offline in the guild window.
- What `GetGuildRosterLastOnline` returns for that false row.
- Whether any populated row lacks a name or character id, and whether any id or name is duplicated.
- Whether `GUILD_ROSTER_UPDATE` fires when the guild window opens, and what argument types it passes.
- Whether the examined count stays 214 on two scans a minute apart.
- Whether a guild larger than 500 exists on this server. This probe would mark that scan partial.

Host tests in `tests/test_ironkeep_roster_probe.lua` do not prove any of this. They only check the probe’s own counting and redaction.
