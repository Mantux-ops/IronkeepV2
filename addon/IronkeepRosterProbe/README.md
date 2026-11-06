# Ironkeep Roster Probe

Development-only. This folder is not part of the Ironkeep addon. It does not read or write `IronkeepDB`, and it does not invite, remove, promote, or edit the guild. Delete the folder when the check is finished.

## Install on WoW Forever

1. Copy this folder to `Interface\AddOns\IronkeepRosterProbe` inside the Forever client directory. The game directory used by the Companion is `World of Warcraft\_forever_`.
2. Leave the existing `Interface\AddOns\Ironkeep` folder unchanged.
3. Enable **Ironkeep Roster Probe** on the addons list. It has no dependency on Ironkeep.
4. Log in with the guild character, or `/reload`.

The chat line `Ironkeep probe loaded` means the addon started. The interface version matches Ironkeep: `16001`.

## Test

1. Read the lines printed after entering the world.
2. Type `/ikprobe` once.
3. If the member count is missing, zero, or every roster call returns nil, open the guild window and type `/ikprobe` again. `GuildRoster` is not called, because that call can ask the server for data.
4. Type `/ikprobe` once more after the guild window has been open. The `GUILD_ROSTER_UPDATE` line should change if the client sends that event.
5. Compare the boolean counts and `GetNumGuildMembers` numbers with the guild window. Do not paste the whole chat log into a ticket if it contains the guild name and you would rather not share it.

## What the chat shows

- Whether each watched name is `nil` or a `function`. Functions that would change the guild, including `GuildRoster`, are reported and not called.
- `IsInGuild` and `GetGuildInfo("player")`. Guild-info strings are shown, capped at 40 characters, because they identify the guild rather than a roster row.
- Every return from `GetNumGuildMembers`, without naming which number means online.
- One pass over at most 200 members. The chat shows counts only, then one sample row: your own row when a return matches `UnitName`, `UnitFullName`, or the first `UnitFullName` value. Other strings are reduced to their length. Zones, notes, character names, and character ids are not printed.
- Boolean fields as `true` and `false` counts. A `false` count means `GetGuildRosterInfo` returned that row. It does not by itself prove the flag means offline.
- Whether `GUILD_ROSTER_UPDATE` could be registered and how many times it has fired since login.

## Still needs the Forever client

- Which `GetGuildRosterInfo` return is name, level, class, rank, online, or id, if the match lines do not appear.
- Whether offline members are in the count when the guild window shows them offline.
- Whether the cache stays empty until the guild window is opened.
- The arguments of `GUILD_ROSTER_UPDATE`, and whether it fires without `GuildRoster`.
- What `GetNumGuildMembers` and `GetGuildRosterLastOnline` return on this client.
