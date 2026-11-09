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

local frames = {}
function CreateFrame()
	local frame = { _events = {}, _scripts = {}, _shown = false }
	function frame:RegisterEvent(event)
		self._events[#self._events + 1] = event
	end
	function frame:SetScript(name, fn)
		self._scripts[name] = fn
	end
	function frame:Show() self._shown = true end
	function frame:Hide() self._shown = false end
	frames[#frames + 1] = frame
	return frame
end

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

local watch = frames[1]
assertTrue(watch ~= nil, "the roster addon did not create a frame")
local registeredUpdate = false
for i = 1, #watch._events do
	if watch._events[i] == "GUILD_ROSTER_UPDATE" then registeredUpdate = true end
end
assertTrue(registeredUpdate, "GUILD_ROSTER_UPDATE was not registered")
assertEqual(#watch._events, 1, "the roster addon registered an extra event")
assertTrue(watch._shown == false, "the roster frame stays shown while idle")

install(214, 110)
local calls = 0
local depth = 0
local maxDepth = 0
local lastInfo
local inner = IronkeepRoster.Scan
IronkeepRoster.Scan = function(mode)
	depth = depth + 1
	if depth > maxDepth then maxDepth = depth end
	calls = calls + 1
	local info = inner(mode)
	lastInfo = info
	depth = depth - 1
	return info
end
local function fire()
	watch._scripts.OnEvent(watch, "GUILD_ROSTER_UPDATE")
end
local function elapse(seconds)
	watch._scripts.OnUpdate(watch, seconds)
end
local quiet = IronkeepRoster.QUIET_SECONDS
fire()
fire()
fire()
elapse(quiet - 0.1)
assertEqual(calls, 0, "a burst scanned before the quiet period")
fire()
elapse(quiet - 0.1)
assertEqual(calls, 0, "a new event did not restart the quiet period")
printed = {}
elapse(quiet)
assertEqual(calls, 1, "the quiet period did not scan once")
assertEqual(maxDepth, 1, "a roster scan overlapped another scan")
local identical = lastInfo
assertEqual(identical.reason, "unchanged")
assertTrue(not identical.published, "an identical roster was published")
assertTrue(IronkeepRosterDB == previous, "an identical automatic scan replaced the snapshot")
assertEqual(chat(), "", "an identical automatic scan printed chat")
assertTrue(IronkeepDB == saved, "an automatic scan replaced attendance data")

install(216, 110)
printed = {}
local grown = inner("auto")
assertTrue(grown.published, "a larger roster was not captured automatically")
assertEqual(#IronkeepRosterDB.members, 216)
assertEqual(chat(), "", "a routine automatic save printed chat")
local grownSaved = IronkeepRosterDB

install(210, 100)
printed = {}
local shrunk = inner("auto")
assertEqual(shrunk.reason, "suspicious-drop")
assertTrue(not shrunk.published, "a sharp drop was published automatically")
assertTrue(IronkeepRosterDB == grownSaved, "a sharp drop replaced the snapshot")
assertTrue(string.find(chat(), "/ikroster", 1, true) ~= nil, "a sharp drop did not tell the officer about /ikroster")
printed = {}
local shrunkAgain = inner("auto")
assertEqual(shrunkAgain.reason, "suspicious-drop")
assertEqual(chat(), "", "a repeated sharp drop printed again")

install(212, 100)
printed = {}
local smallDrop = inner("auto")
assertTrue(smallDrop.published, "a drop of four members was rejected")
assertEqual(#IronkeepRosterDB.members, 212)
assertEqual(chat(), "", "a small automatic drop printed chat")

install(206, 100)
local sharp = inner("auto")
assertEqual(sharp.reason, "suspicious-drop")
assertEqual(#IronkeepRosterDB.members, 212, "the second sharp drop replaced the snapshot")
printed = {}
local manualSmaller = SlashCmdList.IKROSTER()
assertTrue(manualSmaller.published, "/ikroster did not save the smaller roster")
assertEqual(#IronkeepRosterDB.members, 206)
assertTrue(string.find(chat(), "Guild roster saved. 206 members for Herberg.", 1, true) ~= nil, "the manual save was not reported")

local held = IronkeepRosterDB
printed = {}
install(5, 2, function(index)
	if index == 3 then return "empty" end
end)
local partialAuto = inner("auto")
assertEqual(partialAuto.reason, "incomplete")
assertTrue(IronkeepRosterDB == held, "an incomplete automatic scan replaced the snapshot")
assertEqual(chat(), "", "an incomplete automatic scan printed chat")

printed = {}
_G.IsInGuild = function() return false end
local left = inner("auto")
assertEqual(left.reason, "not-in-guild")
assertTrue(IronkeepRosterDB == held, "leaving the guild cleared the snapshot")
assertEqual(chat(), "", "leaving the guild printed chat")

install(206, 100)
printed = {}
local current = SlashCmdList.IKROSTER()
assertEqual(current.reason, "unchanged")
assertTrue(IronkeepRosterDB == held, "a manual rescan replaced an identical snapshot")
assertTrue(string.find(chat(), "already current", 1, true) ~= nil, "the manual rescan did not say the roster is current")

install(206, 100, function(index)
	if index == 2 then return "custom", "Person3", "Member", 60, "Mage", "MAGE", "G-3" end
	if index == 3 then return "custom", "Person2", "Member", 60, "Mage", "MAGE", "G-2" end
end)
local reordered = SlashCmdList.IKROSTER()
assertEqual(reordered.reason, "unchanged")
assertTrue(IronkeepRosterDB == held, "reordered identical members replaced the snapshot")

calls = 0
maxDepth = 0
IronkeepRoster.Scan = function(mode)
	depth = depth + 1
	if depth > maxDepth then maxDepth = depth end
	calls = calls + 1
	local info = inner(mode)
	depth = depth - 1
	return info
end
install(208, 100)
local poked = false
_G.GetGuildRosterInfo = function(index)
	if not poked then
		poked = true
		elapse(quiet + 1)
		fire()
	end
	if index == 1 then
		return fields("Ada Smith", "Member", 70, "Warrior", "WARRIOR", "Player-5826-0A1")
	end
	return fields("Person" .. index, "Member", 60, "Mage", "MAGE", "G-" .. index)
end
fire()
elapse(quiet)
assertEqual(calls, 1, "an event during a scan started a second scan")
assertEqual(maxDepth, 1, "a scan re-entered itself")
elapse(quiet)
assertEqual(calls, 2, "an event during a scan did not run after the next quiet period")
elapse(30)
assertEqual(calls, 2, "the roster addon scanned without a new event")
IronkeepRoster.Scan = inner

assertEqual(guildRosterCalls, 0, "GuildRoster was called")
assertEqual(IronkeepDB.session.people.a.name, "Ada Smith")
assertTrue(IronkeepDB == saved, "roster capture replaced attendance data")

io.write("ok\n")
