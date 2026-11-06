-- Host check for the development probe. This does not run inside WoW Forever.

local printed = {}
function print(message) printed[#printed + 1] = tostring(message) end

local frames = {}
function CreateFrame()
	local frame = { _scripts = {} }
	function frame:SetScript(name, fn) self._scripts[name] = fn end
	function frame:RegisterEvent(name)
		self._events = self._events or {}
		self._events[name] = true
	end
	frames[#frames + 1] = frame
	return frame
end

local guildRosterCalls = 0
SlashCmdList = {}
_G.GuildRoster = function()
	guildRosterCalls = guildRosterCalls + 1
	error("GuildRoster must not be called")
end
_G.GuildInvite = function() error("GuildInvite must not be called") end

local function assertTrue(value, message)
	if not value then error(message or "check failed", 2) end
end

local function textOf(lines)
	return table.concat(printed, "\n") .. "\n" .. table.concat(lines or {}, "\n")
end

local function run(message)
	printed = {}
	local lines = SlashCmdList.IKPROBE(message)
	return textOf(lines), lines
end

local function assertHas(text, needle)
	if not string.find(text, needle, 1, true) then
		error("missing [" .. needle .. "]\n" .. text, 2)
	end
end

local function assertMissing(text, needle)
	if string.find(text, needle, 1, true) then
		error("printed [" .. needle .. "]\n" .. text, 2)
	end
end

local function forbid(text, needles)
	local i
	for i = 1, #needles do assertMissing(text, needles[i]) end
end

local secrets = {
	"Ada", "Bram", "Cara", "Holt", "Quinn", "Stormwind", "Shattrath",
	"public note", "hidden plaque", "Player-5826", "WARRIOR", "MAGE", "PRIEST",
	"Hall of Thanes", "Officer", "SecretName", "SecretZone", "SecretNote",
	"SecretGuid", "DupToken", "DupGuid", "OtherToken", "OtherGuid",
}

local marker = {}
local oddFunction = function() end

local function installBase()
	_G.IsInGuild = function() return true end
	_G.GetGuildInfo = function(unit)
		assert(unit == "player")
		return "Herberg", "Member", 4
	end
	_G.GetNumGuildMembers = function() return 3, 2 end
	_G.UnitName = function() return "Ada Smith" end
	_G.UnitFullName = function() return "Ada", "Smith" end
	_G.UnitClass = function() return "Warrior", "WARRIOR" end
	_G.UnitLevel = function() return 70 end
	_G.UnitGUID = function() return "Player-5826-0A1" end
	_G.GetGuildRosterInfo = function(index)
		if index == 1 then
			return "Bram Holt", "Officer", 2, 63, "Mage", "Stormwind", "public note", "", false, "", "MAGE", 1, true, nil, "hidden plaque", marker, "Player-5826-0B2"
		end
		if index == 2 then
			return "Ada Smith", "Member", 4, 70, "Warrior", "Hall of Thanes", "", "", true, "", "WARRIOR", 2, true, nil, "", nil, "Player-5826-0A1"
		end
		return "Cara Quinn", "Member", 4, 28, "Priest", "Shattrath", "", "", true, "", "PRIEST", oddFunction, true, nil, "", nil, "Player-5826-0C3"
	end
	_G.GetGuildRosterLastOnline = function(index)
		if index == 2 then return nil, nil, nil, nil end
		return 1, 2, 3, 4
	end
end

local function installMany(count)
	_G.GetNumGuildMembers = function()
		return count, math.floor(count / 2)
	end
	_G.GetGuildRosterInfo = function(index)
		local online = index <= math.floor(count / 2)
		return "SecretName" .. index, "Rank", 1, 10, "Warrior", "SecretZone", "SecretNote", "", online, "", "WARRIOR", 1, false, nil, "", nil, "SecretGuid" .. index
	end
	_G.GetGuildRosterLastOnline = function() return nil, nil, nil, nil end
end

installBase()
dofile("addon/IronkeepRosterProbe/Probe.lua")

assertTrue(SlashCmdList.IKPROBE, "slash command was not registered")
assertTrue(IronkeepRosterProbe.SCAN_CAP >= 500, "safety cap is below 500")

local overview = run()
assertHas(overview, "GetGuildRosterInfo = function")
assertHas(overview, "GuildRoster = function (present, not called)")
assertHas(overview, "IsInGuild returns boolean true")
assertHas(overview, "text=[Herberg]")
assertHas(overview, "Scan: complete. Examined 3, populated 3, empty 0, errors 0. Cap 500.")
assertHas(overview, "GetNumGuildMembers #1=3 #2=2.")
assertHas(overview, "Your row was index 2.")
assertHas(overview, "Widest populated row returned 17 values.")
assertHas(overview, "Online candidate: field #9 true 2, false 1; true equals count #2. Candidate only.")
assertMissing(overview, "Online candidate: field #13")
assertHas(overview, "Online-status mapping remains unverified.")
assertHas(overview, "Populated rows equal count #1, and count #2 is smaller.")
assertHas(overview, "GetGuildRosterLastOnline(your index 2): nil, nil, nil, nil.")
assertHas(overview, "Nil does not mean the function is broken.")
assertHas(overview, "GetGuildRosterLastOnline(index 1 where field #9 is false): number, number, number, number.")
assertHas(overview, "Received 0 time(s) since login")
forbid(overview, secrets)

local fields = run(" fields ")
assertHas(fields, "Scan: complete.")
assertHas(fields, "#1 seen 3, nil 0, non-nil 3")
assertHas(fields, "player matches UnitName")
assertHas(fields, "matches UnitFullName joined")
assertHas(fields, "matches the guild rank from GetGuildInfo")
assertHas(fields, "equals your level")
assertHas(fields, "matches your localized class")
assertHas(fields, "matches your class file token")
assertHas(fields, "matches your character id")
assertHas(fields, "#9 seen 3, nil 0, non-nil 3; boolean 3; true 2, false 1")
assertHas(fields, "function 1")
assertHas(fields, "table 1")
assertHas(fields, "number range 28 to 70")
assertHas(fields, "Online-status mapping remains unverified.")
forbid(fields, secrets)

local identity = run("identity")
assertHas(identity, "Name field #1")
assertHas(identity, "non-empty 3, missing 0, other types 0, duplicate values 0, extra copies 0")
assertHas(identity, "GUID field #17")
assertHas(identity, "Format was not checked.")
forbid(identity, secrets)

local eventFrame
local i
for i = 1, #frames do
	if frames[i]._scripts.OnEvent then eventFrame = frames[i] end
end
assertTrue(eventFrame and eventFrame._events.GUILD_ROSTER_UPDATE, "the roster event was not registered")
eventFrame._scripts.OnEvent(eventFrame, "GUILD_ROSTER_UPDATE", true)
local events = run("events")
assertHas(events, "The roster was not scanned")
assertHas(events, "Received 1 time(s) since login, 1 since the previous probe command.")
assertHas(events, "Last arguments: boolean true")
forbid(events, secrets)
local eventsAgain = run("events")
assertHas(eventsAgain, "Received 1 time(s) since login, 0 since the previous probe command.")

installMany(250)
local over200 = run()
assertHas(over200, "Scan: complete. Examined 250, populated 250, empty 0, errors 0. Cap 500.")
assertMissing(over200, "Scan: partial")
forbid(over200, secrets)

installMany(500)
local exact = run()
assertHas(exact, "Scan: complete. Examined 500, populated 500, empty 0, errors 0. Cap 500.")
forbid(exact, secrets)

installMany(IronkeepRosterProbe.SCAN_CAP + 1)
local capped = run()
assertHas(capped, "Scan: partial. Examined 500, populated 500, empty 0, errors 0. Cap 500. Reason: safety cap. Reported count was 501.")
assertHas(capped, "Boolean comparison needs a complete scan. Online-status mapping remains unverified.")
assertMissing(capped, "Scan: complete")
forbid(capped, secrets)

local reads = 0
_G.GetNumGuildMembers = function()
	reads = reads + 1
	if reads == 1 then return 10, 4 end
	return 12, 5
end
_G.GetGuildRosterInfo = function(index)
	local online = index <= 4
	return "SecretName" .. index, "Rank", 1, 10, "Warrior", "SecretZone", "SecretNote", "", online, "", "WARRIOR", 1, false, nil, "", nil, "SecretGuid" .. index
end
local changed = run()
assertHas(changed, "Scan: partial.")
assertHas(changed, "Reason: member count changed.")
assertHas(changed, "Later reading #1=12 #2=5.")
assertHas(changed, "Examined 10")
assertMissing(changed, "Scan: complete")
forbid(changed, secrets)

_G.GetNumGuildMembers = function() return 5, 3 end
_G.GetGuildRosterInfo = function(index)
	if index == 2 then return end
	if index == 3 then return nil, nil end
	return "SecretName" .. index, "Rank", 1, 10, "Warrior", "SecretZone", "SecretNote", "", true, "", "WARRIOR", 1, false, nil, "", nil, "SecretGuid" .. index
end
local holes = run()
assertHas(holes, "Scan: complete. Examined 5, populated 3, empty 2, errors 0. Cap 500.")
forbid(holes, secrets)

local dupNames = { "Ada Smith", "DupToken", "DupToken", "", nil, "OtherToken" }
local dupGuids = { "Player-5826-0A1", "DupGuid", "DupGuid", "", nil, "OtherGuid" }
_G.GetNumGuildMembers = function() return 6, 6 end
_G.GetGuildRosterInfo = function(index)
	return dupNames[index], "Rank", 1, 70, "Warrior", "SecretZone", "SecretNote", "", true, "", "WARRIOR", 1, true, nil, "", nil, dupGuids[index]
end
local dup = run("identity")
assertHas(dup, "Scan: complete.")
assertHas(dup, "Name field #1 (scanned rows): non-empty 4, missing 2, other types 0, duplicate values 1, extra copies 1.")
assertHas(dup, "GUID field #17 (scanned rows): non-empty 4, missing 2, other types 0, duplicate values 1, extra copies 1.")
assertHas(dup, "Format was not checked.")
forbid(dup, secrets)

_G.GetNumGuildMembers = function() return 5, 2 end
_G.GetGuildRosterInfo = function(index)
	if index == 2 or index == 4 then error("scan failed") end
	return "SecretName" .. index, "Rank", 1, 10, "Warrior", "SecretZone", "SecretNote", "", true, "", "WARRIOR", 1, false, nil, "", nil, "SecretGuid" .. index
end
local failed = run()
assertHas(failed, "Scan: partial.")
assertHas(failed, "Examined 5, populated 3, empty 0, errors 2.")
assertHas(failed, "Reason: API errors.")
assertHas(failed, "API errors: 2.")
assertHas(failed, "scan failed")
assertMissing(failed, "Scan: complete")
forbid(failed, secrets)

_G.GetNumGuildMembers = function() return 3 end
_G.GetGuildRosterInfo = function(index)
	return "SecretName" .. index, "Rank", 1, 10, "Warrior", "SecretZone", "SecretNote", "", true, "", "WARRIOR", 1, false, nil, "", nil, "SecretGuid" .. index
end
local oneCount = run()
assertHas(oneCount, "GetNumGuildMembers #1=3.")
assertHas(oneCount, "Count #2 was not a number, so no online candidate was chosen.")
assertHas(oneCount, "Online-status mapping remains unverified.")
assertMissing(oneCount, "Online candidate: field #")
forbid(oneCount, secrets)

_G.GetGuildRosterInfo = function() error("failed for Ada Smith") end
_G.GetNumGuildMembers = function() return 1, 1 end
local redacted = run()
assertHas(redacted, "[redacted]")
assertHas(redacted, "errors 1")
assertMissing(redacted, "Ada")

local rosterCalls = 0
_G.GetGuildRosterInfo = function()
	rosterCalls = rosterCalls + 1
	return "SecretName", "Rank", 1, 70, "Warrior", "SecretZone", "SecretNote", "", true, "", "WARRIOR", 1, true, nil, "", nil, "Player-5826-0A1"
end
_G.GetNumGuildMembers = function() return 1, 1 end
local before = rosterCalls
run("events")
assertTrue(rosterCalls == before, "the events command scanned the roster")
local unknown = run("nope")
assertHas(unknown, "Unknown command.")
assertTrue(rosterCalls == before, "an unknown command scanned the roster")

for name, _ in pairs({
	IsInGuild = true, GetGuildInfo = true, GetNumGuildMembers = true,
	GetGuildRosterInfo = true, GetGuildRosterLastOnline = true, UnitName = true,
	UnitFullName = true, UnitClass = true, UnitLevel = true, UnitGUID = true,
}) do
	_G[name] = nil
end
local bare = run()
assertHas(bare, "GetGuildRosterInfo = nil")
assertHas(bare, "GetGuildRosterInfo was not called.")
assertHas(bare, "IsInGuild was not called.")
assertHas(bare, "Scan: not run.")
assertMissing(bare, "Scan: complete")
assertMissing(bare, "Scan: partial")

assertTrue(guildRosterCalls == 0, "GuildRoster was called")
io.write("ok\n")
