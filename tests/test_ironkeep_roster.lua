-- Host checks for the guild roster snapshot. This does not run inside WoW Forever.

local printed = {}
function print(message) printed[#printed + 1] = tostring(message) end

local guildRosterCalls = 0
_G.GuildRoster = function()
	guildRosterCalls = guildRosterCalls + 1
	error("GuildRoster must not be called")
end

local now = 1700002222
function time() return now end

Ironkeep = {}
function Ironkeep.Print(message)
	print("|cff2dd4bfIronkeep|r " .. tostring(message))
end

local saved = { open = true, session = { place = "Hall of Thanes", people = { a = { name = "Ada Smith" } } } }
IronkeepDB = saved
local previous = { schema = 1, marker = "keep-me", members = { { guid = "old", name = "Old Name" } } }
IronkeepRosterDB = previous

dofile("addon/IronkeepRoster/Roster.lua")

local function assertTrue(value, message)
	if not value then error(message or "check failed", 2) end
end

local function assertEqual(actual, expected, message)
	if actual ~= expected then
		error((message or "mismatch") .. ": " .. tostring(actual) .. " ~= " .. tostring(expected), 2)
	end
end

assertTrue(IronkeepRosterDB == previous, "loading the roster addon replaced an existing snapshot")
assertTrue(IronkeepDB == saved, "loading the roster addon replaced attendance data")

local function savedVariables(path)
	local handle = io.open(path, "r")
	if not handle then error("missing " .. path) end
	local text = handle:read("*a")
	handle:close()
	local line = string.match(text, "## SavedVariables:%s*([^\n]+)")
	return text, line
end

local ironkeepText, ironkeepSaved = savedVariables("addon/Ironkeep/Ironkeep.toc")
local rosterText, rosterSaved = savedVariables("addon/IronkeepRoster/IronkeepRoster.toc")
assertEqual(ironkeepSaved, "IronkeepDB", "attendance SavedVariables")
assertEqual(rosterSaved, "IronkeepRosterDB", "roster SavedVariables")
assertTrue(string.find(ironkeepText, "Roster.lua", 1, true) == nil, "Ironkeep still loads the roster file")
assertTrue(string.find(rosterText, "\nRoster.lua", 1, true) ~= nil, "the roster addon does not load Roster.lua")
assertTrue(string.find(rosterText, "OptionalDeps: Ironkeep", 1, true) ~= nil, "Ironkeep is not loaded first")
assertTrue(string.find(ironkeepText, "IronkeepRosterDB", 1, true) == nil, "Ironkeep still saves the roster global")

local function chat()
	return table.concat(printed, "\n")
end

local function assertMissing(text, needle)
	if string.find(text, needle, 1, true) then
		error("printed [" .. needle .. "]\n" .. text, 2)
	end
end

local function walk(value, seen, hit)
	if type(value) ~= "table" or seen[value] then return end
	seen[value] = true
	for key, item in pairs(value) do
		if key == "ZoneSecret" or key == "NoteSecret" or key == "online" or key == "rankIndex" or key == "note" then
			hit[key] = true
		end
		if item == "ZoneSecret" or item == "NoteSecret" then hit[item] = true end
		walk(key, seen, hit)
		walk(item, seen, hit)
	end
end

local function kept()
	assertTrue(IronkeepRosterDB == previous, "a failed scan replaced the snapshot")
	assertEqual(#IronkeepRosterDB.members, 214, "the saved member list changed")
	assertEqual(IronkeepRosterDB.members[1].guid, "Player-5826-0A1", "the saved player changed")
	assertTrue(IronkeepDB == saved, "IronkeepDB was replaced")
	assertEqual(IronkeepDB.session.place, "Hall of Thanes", "the group place changed")
end

local function fields(name, rank, level, className, classToken, guid)
	return name, rank, 1, level, className, "ZoneSecret", "NoteSecret", "", true, "", classToken, false, false, false, false, false, guid
end

local function install(count, online, mutate)
	_G.IsInGuild = function() return true end
	_G.GetGuildInfo = function(unit)
		assert(unit == "player")
		return "Herberg", "Member", 4
	end
	_G.GetNumGuildMembers = function() return count, online end
	_G.UnitName = function() return "Ada Smith" end
	_G.UnitFullName = function() return "Ada", "Smith" end
	_G.UnitClass = function() return "Warrior", "WARRIOR" end
	_G.UnitLevel = function() return 70 end
	_G.UnitGUID = function() return "Player-5826-0A1" end
	_G.GetGuildRosterInfo = function(index)
		if mutate then
			local kind, name, rank, level, className, classToken, guid = mutate(index)
			if kind == "empty" then return end
			if kind == "custom" then return fields(name, rank, level, className, classToken, guid) end
		end
		if index == 1 then
			return fields("Ada Smith", "Member", 70, "Warrior", "WARRIOR", "Player-5826-0A1")
		end
		return fields("Person" .. index, "Member", 60, "Mage", "MAGE", "G-" .. index)
	end
end

install(0, 0)
printed = {}
local emptyFirst = IronkeepRoster.Scan()
assertEqual(emptyFirst.reason, "empty")
assertTrue(IronkeepRosterDB == previous, "an empty guild replaced the existing snapshot")
assertEqual(IronkeepRosterDB.marker, "keep-me")

install(214, 110)
printed = {}
local published = IronkeepRoster.Scan()
assertTrue(published.published, "the 214 member roster was not published")
assertEqual(published.reason, "published")
assertEqual(published.examined, 214)
assertEqual(published.populated, 214)
assertEqual(published.empty, 0)
assertEqual(published.errors, 0)
assertEqual(IronkeepRosterDB.schema, 1)
assertEqual(IronkeepRosterDB.wowGuildName, "Herberg")
assertEqual(IronkeepRosterDB.capturedAt, now)
assertEqual(IronkeepRosterDB.completeness.status, "complete")
assertEqual(IronkeepRosterDB.completeness.reportedTotal, 214)
assertEqual(IronkeepRosterDB.completeness.reportedOnline, 110)
assertEqual(IronkeepRosterDB.completeness.countStable, true)
assertEqual(IronkeepRosterDB.playerChecks.guidField, 17)
assertEqual(IronkeepRosterDB.playerChecks.nameField, 1)
assertEqual(IronkeepRosterDB.playerChecks.classTokenField, 11)
assertEqual(#IronkeepRosterDB.members, 214)
assertEqual(IronkeepRosterDB.members[1].guid, "Player-5826-0A1")
assertEqual(IronkeepRosterDB.members[1].name, "Ada Smith")
assertEqual(IronkeepRosterDB.members[1].level, 70)
assertEqual(IronkeepRosterDB.members[1].classToken, "WARRIOR")
assertEqual(IronkeepRosterDB.members[1].className, "Warrior")
assertEqual(IronkeepRosterDB.members[1].rankName, "Member")
assertEqual(IronkeepRosterDB.members[214].guid, "G-214")
assertTrue(IronkeepRosterDB.members[1].online == nil, "online status was stored")
assertTrue(IronkeepRosterDB.members[1].rankIndex == nil, "rank index was stored")
assertTrue(IronkeepRosterDB.members[1].note == nil, "a note was stored")
local leaked = {}
walk(IronkeepRosterDB, {}, leaked)
assertTrue(not leaked.ZoneSecret and not leaked.NoteSecret, "a zone or note was stored")
local text = chat()
assertTrue(string.find(text, "Guild roster saved. 214 members for Herberg.", 1, true) ~= nil, "the summary was not printed")
assertMissing(text, "Person50")
assertMissing(text, "ZoneSecret")
assertMissing(text, "NoteSecret")
assertTrue(IronkeepDB == saved, "publishing a roster replaced IronkeepDB")
previous = IronkeepRosterDB

install(0, 0)
printed = {}
local empty = SlashCmdList.IKROSTER()
assertEqual(empty.reason, "empty")
assertTrue(not empty.published, "an empty guild was published")
kept()

install(5, 2, function(index)
	if index == 3 then return "empty" end
end)
printed = {}
local partial = IronkeepRoster.Scan()
assertEqual(partial.reason, "incomplete")
assertTrue(not partial.published)
assertEqual(partial.examined, 5)
assertEqual(partial.empty, 1)
kept()

install(4, 2, function(index)
	if index == 2 then
		return "custom", "Person2", "Member", 60, "Mage", "MAGE", "Player-5826-0A1"
	end
end)
printed = {}
local dupGuid = IronkeepRoster.Scan()
assertEqual(dupGuid.reason, "duplicate-guid")
assertTrue(not dupGuid.published)
assertMissing(chat(), "Player-5826-0A1")
kept()

install(4, 2, function(index)
	if index == 3 then
		return "custom", "Person2", "Officer", 12, "Priest", "PRIEST", "G-3"
	end
end)
printed = {}
local dupName = IronkeepRoster.Scan()
assertEqual(dupName.reason, "duplicate-name")
assertTrue(not dupName.published)
assertMissing(chat(), "Person2")
kept()

install(4, 2, function(index)
	if index == 4 then
		return "custom", "Person4", "Member", 60, "Mage", "MAGE", ""
	end
end)
printed = {}
local missing = IronkeepRoster.Scan()
assertEqual(missing.reason, "missing-guid")
assertTrue(not missing.published)
kept()

install(4, 2, function(index)
	if index == 4 then
		return "custom", "", "Member", 60, "Mage", "MAGE", "G-4"
	end
end)
printed = {}
local missingName = IronkeepRoster.Scan()
assertEqual(missingName.reason, "missing-name")
assertTrue(not missingName.published)
kept()

local reads = 0
install(6, 2)
_G.GetNumGuildMembers = function()
	reads = reads + 1
	if reads == 1 then return 6, 2 end
	return 8, 4
end
printed = {}
local changed = IronkeepRoster.Scan()
assertEqual(changed.reason, "count-changed")
assertTrue(not changed.published)
assertEqual(changed.countStable, false)
kept()

install(IronkeepRoster.SCAN_CAP + 1, 200)
printed = {}
local capped = IronkeepRoster.Scan()
assertEqual(capped.reason, "partial-cap")
assertTrue(not capped.published)
assertEqual(capped.examined, 500)
assertEqual(capped.reportedTotal, 501)
kept()
assertEqual(#IronkeepRosterDB.members, 214, "the cap scan replaced the saved roster")

assertEqual(guildRosterCalls, 0, "GuildRoster was called")
assertEqual(IronkeepDB.session.people.a.name, "Ada Smith")

io.write("ok\n")
