-- Host check for the temporary roster diff. This does not run inside WoW Forever.

local guildRosterCalls = 0
_G.GuildRoster = function()
	guildRosterCalls = guildRosterCalls + 1
	error("GuildRoster must not be called")
end

local function fields(name, rank, level, className, classToken, guid)
	return name, rank, 1, level, className, "ZoneSecret", "NoteSecret", "", true, "", classToken, false, false, false, false, false, guid
end

local roster = {
	{ "Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1" },
	{ "Bram Holt", "Officer", 60, "Mage", "MAGE", "G-2" },
}

local function install()
	_G.IsInGuild = function() return true end
	_G.GetGuildInfo = function(unit)
		assert(unit == "player")
		return "Herberg", "Member", 4
	end
	_G.GetNumGuildMembers = function() return #roster, 1 end
	_G.UnitName = function() return "Ada Smith" end
	_G.UnitFullName = function() return "Ada", "Smith" end
	_G.UnitClass = function() return "Warrior", "WARRIOR" end
	_G.UnitLevel = function() return 70 end
	_G.UnitGUID = function() return "G-1" end
	_G.GetGuildRosterInfo = function(index)
		local row = roster[index]
		if not row then return end
		return fields(row[1], row[2], row[3], row[4], row[5], row[6])
	end
end

local function savedFrom(rows, guild)
	local members = {}
	local i
	for i = 1, #rows do
		local row = rows[i]
		members[i] = {
			guid = row[6],
			name = row[1],
			level = row[3],
			className = row[4],
			classToken = row[5],
			rankName = row[2],
		}
	end
	return {
		schema = 1,
		wowGuildName = guild or "Herberg",
		capturedAt = 1794249118,
		members = members,
	}
end

local function fail(message)
	error(message or "check failed", 2)
end

local function assertTrue(value, message)
	if not value then fail(message) end
end

local function assertEqual(actual, expected, message)
	if actual ~= expected then
		fail((message or "mismatch") .. ": " .. tostring(actual) .. " ~= " .. tostring(expected))
	end
end

install()
IronkeepRosterDB = savedFrom(roster)
local original = IronkeepRosterDB
dofile("addon/IronkeepRosterDiag/Diag.lua")

local function find(list, guid, field)
	local i
	for i = 1, #list do
		if list[i].guid == guid and (field == nil or list[i].field == field) then return list[i] end
	end
end

local same = IronkeepRosterDiag.Compare()
assertTrue(same.comparable, "an exact roster was not comparable")
assertTrue(same.sameRoster, "the PR #62 rule did not call an exact roster identical")
assertEqual(#same.added, 0)
assertEqual(#same.removed, 0)
assertEqual(#same.changed, 0)
assertEqual(same.savedWalk, 2)
assertEqual(same.savedHash, 2)
assertEqual(same.liveRows, 2)
assertTrue(IronkeepRosterDB == original, "the diff replaced the saved snapshot")
assertEqual(original.capturedAt, 1794249118, "the diff changed capturedAt")

roster[2][3] = 61
local leveled = IronkeepRosterDiag.Compare()
assertTrue(leveled.comparable)
assertTrue(not leveled.sameRoster, "a level change was treated as identical")
local levelChange = find(leveled.changed, "G-2", "level")
assertTrue(levelChange ~= nil, "the level change was not reported")
assertEqual(tostring(levelChange.old), "60")
assertEqual(tostring(levelChange.new), "61")
assertEqual(#leveled.added, 0)
assertEqual(#leveled.removed, 0)

roster[2][1] = "Bram Stone"
roster[2][2] = "Member"
roster[2][4] = "Priest"
roster[2][5] = "PRIEST"
local edited = IronkeepRosterDiag.Compare()
assertTrue(find(edited.changed, "G-2", "name") ~= nil, "the name change was not reported")
assertTrue(find(edited.changed, "G-2", "rank") ~= nil, "the rank change was not reported")
assertTrue(find(edited.changed, "G-2", "class") ~= nil, "the class change was not reported")
assertTrue(find(edited.changed, "G-2", "class token") ~= nil, "the class token change was not reported")

roster = {
	{ "Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1" },
	{ "Cara Quinn", "Member", 58, "Hunter", "HUNTER", "G-3" },
}
local swapped = IronkeepRosterDiag.Compare()
assertTrue(find(swapped.removed, "G-2") ~= nil, "the removed guid was not reported")
assertTrue(find(swapped.added, "G-3") ~= nil, "the added guid was not reported")
assertTrue(not swapped.sameRoster)

roster = {
	{ "Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1" },
	{ "", "Member", 60, "Mage", "MAGE", "" },
}
local missing = IronkeepRosterDiag.Compare()
assertTrue(not missing.comparable, "a missing guid still reached sameRoster")
assertEqual(missing.blocked, "missing-guid")
assertEqual(missing.liveMissingGuid, 1)
assertTrue(not missing.sameRoster)

roster = {
	{ "Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1" },
}
_G.GetGuildRosterInfo = function(index)
	if index == 1 then
		return fields("Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1")
	end
end
_G.GetNumGuildMembers = function() return 2, 1 end
local incomplete = IronkeepRosterDiag.Compare()
assertTrue(not incomplete.comparable, "an empty row still reached sameRoster")
assertEqual(incomplete.liveEmpty, 1)
assertEqual(incomplete.blocked, nil)

IronkeepRosterDB = {
	schema = 1,
	wowGuildName = "Herberg",
	capturedAt = 1794249118,
	members = {
		["1"] = {
			guid = "G-1",
			name = "Ada Smith",
			level = 70,
			classToken = "WARRIOR",
			className = "Warrior",
			rankName = "Member",
		},
	},
}
roster = {
	{ "Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1" },
}
install()
local hashed = IronkeepRosterDiag.Compare()
assertEqual(hashed.savedHash, 0, "a string key was counted by the length operator")
assertEqual(hashed.savedExtra, 1, "a string key was not reported")
assertTrue(hashed.comparable)
assertTrue(not hashed.sameRoster, "a non-sequence save was treated as identical")
assertEqual(#hashed.added, 0)
assertEqual(#hashed.removed, 0)
assertEqual(#hashed.changed, 0)

assertEqual(guildRosterCalls, 0, "GuildRoster was called")
assertEqual(IronkeepRosterDB.capturedAt, 1794249118)

local function contains(text, needle)
	if string.find(tostring(text), needle, 1, true) == nil then
		fail(needle .. " not found in: " .. tostring(text))
	end
end

assertTrue(IronkeepRosterDiag.OnUpdate == nil, "the diagnostic invented a scan timer")
local unseen = IronkeepRosterDiag.Observation()
assertTrue(not unseen.wrapped, "a missing production scan was treated as wrapped")
assertEqual(unseen.automaticScans, 0)
assertTrue(unseen.last == nil)
local unseenLines = IronkeepRosterDiag.Lines()
contains(unseenLines[1], "no automatic scan observed")
contains(unseenLines[1], "not wrapped")

IronkeepRosterDiag.OnEvent(nil, "GUILD_ROSTER_UPDATE")
IronkeepRosterDiag.OnEvent(nil, "GUILD_ROSTER_UPDATE")
local eventsOnly = IronkeepRosterDiag.Observation()
assertEqual(eventsOnly.automaticScans, 0, "a roster event was counted as a scan")
assertEqual(eventsOnly.rosterEvents, 2)
assertTrue(eventsOnly.last == nil)
contains(IronkeepRosterDiag.Lines()[1], "An event is not a scan.")

local function useScan(fn)
	IronkeepRoster = { Scan = fn }
	assertTrue(IronkeepRosterDiag.Install(), "the production scan was not wrapped")
	assertTrue(IronkeepRoster.Scan ~= fn, "Install left the production function unwrapped")
end

local kept = { capturedAt = 1794316970, members = {} }
IronkeepRosterDB = kept
local calls = 0
local seenArgc
useScan(function(...)
	calls = calls + 1
	seenArgc = select("#", ...)
	return { published = false, reason = "unchanged", populated = 329 }
end)
assertEqual(select("#", IronkeepRoster.Scan()), 1, "the wrapper dropped the scan result")
assertEqual(seenArgc, 0, "a manual scan gained an argument")
assertEqual(calls, 1)
local manual = IronkeepRosterDiag.Observation()
assertEqual(manual.automaticScans, 0, "a manual scan was counted as automatic")
assertEqual(manual.manualScans, 1)
assertTrue(manual.last == nil)
assertTrue(IronkeepRosterDB == kept, "the wrapper replaced the snapshot")
assertEqual(kept.capturedAt, 1794316970)

IronkeepRoster.Scan("auto")
assertEqual(seenArgc, 1)
assertEqual(calls, 2)
local preserved = IronkeepRosterDiag.Observation()
assertEqual(preserved.automaticScans, 1)
assertEqual(preserved.last.outcome, "preserved")
assertEqual(preserved.last.beforeAt, 1794316970)
assertEqual(preserved.last.afterAt, 1794316970)
assertTrue(preserved.last.sameSnapshot)
assertTrue(IronkeepRosterDB == kept)
local preservedLines = IronkeepRosterDiag.Lines()
contains(preservedLines[1], "identical roster, snapshot preserved")
contains(preservedLines[1], "1794316970")
local scansAfterReport = IronkeepRosterDiag.Observation().automaticScans
IronkeepRosterDiag.Lines()
assertEqual(IronkeepRosterDiag.Observation().automaticScans, scansAfterReport, "the report called the production scan")

IronkeepRosterDiag.Install()
IronkeepRoster.Scan("auto")
assertEqual(calls, 3, "wrapping twice called the scan twice")

local previous = kept
useScan(function()
	IronkeepRosterDB = { capturedAt = 1794317000, members = {} }
	return { published = true, reason = "published", populated = 329 }
end)
local publishedInfo = IronkeepRoster.Scan("auto")
assertEqual(publishedInfo.reason, "published")
assertEqual(previous.capturedAt, 1794316970, "the old snapshot was edited in place")
local published = IronkeepRosterDiag.Observation()
assertEqual(published.last.outcome, "published")
assertEqual(published.last.beforeAt, 1794316970)
assertEqual(published.last.afterAt, 1794317000)
assertTrue(not published.last.sameSnapshot)
contains(IronkeepRosterDiag.Lines()[1], "changed roster, new snapshot published")

IronkeepRosterDB = previous
useScan(function()
	return { published = false, reason = "suspicious-drop", populated = 10 }
end)
IronkeepRoster.Scan("auto")
local rejected = IronkeepRosterDiag.Observation()
assertEqual(rejected.last.outcome, "rejected")
assertEqual(rejected.last.reason, "suspicious-drop")
assertTrue(rejected.last.sameSnapshot)
assertEqual(IronkeepRosterDB, previous)
contains(IronkeepRosterDiag.Lines()[1], "scan skipped or rejected (suspicious-drop)")

IronkeepRosterDB = { capturedAt = 5, members = {} }
useScan(function()
	IronkeepRosterDB.capturedAt = 6
	return { published = false, reason = "unchanged" }
end)
IronkeepRoster.Scan("auto")
assertEqual(IronkeepRosterDiag.Observation().last.outcome, "conflict")
local conflictLine = IronkeepRosterDiag.Lines()[1]
assertTrue(string.find(conflictLine, "snapshot preserved", 1, true) == nil, "a contradictory scan was called preserved")
contains(conflictLine, "disagreed")

useScan(function()
	error("boom")
end)
local failed, err = pcall(IronkeepRoster.Scan, "auto")
assertTrue(not failed, "a scan error was swallowed")
contains(err, "boom")
assertEqual(IronkeepRosterDiag.Observation().last.outcome, "error")
contains(IronkeepRosterDiag.Lines()[1], "scan skipped or rejected (error)")

IronkeepRoster = { Scan = function()
	return { published = false, reason = "unchanged" }
end }
IronkeepRosterDiag.OnEvent(nil, "ADDON_LOADED", "IronkeepRoster")
assertTrue(IronkeepRosterDiag.Observation().wrapped, "ADDON_LOADED did not wrap the scan")
local beforeEvent = IronkeepRosterDiag.Observation().automaticScans
IronkeepRosterDiag.OnEvent(nil, "GUILD_ROSTER_UPDATE")
assertEqual(IronkeepRosterDiag.Observation().automaticScans, beforeEvent)

roster = {
	{ "Ada Smith", "Member", 70, "Warrior", "WARRIOR", "G-1" },
	{ "Bram Holt", "Officer", 60, "Mage", "MAGE", "G-2" },
}
install()
IronkeepRosterDB = savedFrom(roster)
roster[2][3] = 61
local detail = IronkeepRosterDiag.Lines()
contains(detail[2], "sameRoster false")
contains(detail[3], "changed G-2 level")

assertEqual(guildRosterCalls, 0, "GuildRoster was called")

io.write("ok\n")
