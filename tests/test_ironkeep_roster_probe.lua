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

SlashCmdList = {}
_G.GuildRoster = function() error("GuildRoster must not be called") end
_G.GuildInvite = function() error("GuildInvite must not be called") end
_G.IsInGuild = function() return true end
_G.GetGuildInfo = function(unit)
	assert(unit == "player")
	return "Herberg", "Member", 4
end
_G.GetNumGuildMembers = function() return 3, 1 end
_G.UnitName = function() return "Ada Smith" end
_G.UnitFullName = function() return "Ada", "Smith" end
_G.UnitClass = function() return "Warrior", "WARRIOR" end
_G.UnitLevel = function() return 70 end
_G.UnitGUID = function() return "Player-5826-0A1" end
_G.GetGuildRosterInfo = function(index)
	if index == 1 then
		return "Bram Holt", "Officer", 2, 63, "Mage", "Stormwind", "public note", "", false, "Player-5826-0B2"
	end
	if index == 2 then
		return "Ada Smith", "Member", 4, 70, "Warrior", "Hall of Thanes", "", "", true, "Player-5826-0A1"
	end
	return "Cara Quinn", "Member", 4, 28, "Priest", "Shattrath", "", "", true, "Player-5826-0C3"
end
_G.GetGuildRosterLastOnline = function() return 0, 0, 1, 2 end

dofile("addon/IronkeepRosterProbe/Probe.lua")

local function joined()
	return table.concat(printed, "\n")
end

local function assertTrue(value, message)
	if not value then error(message or "check failed", 2) end
end

assertTrue(SlashCmdList.IKPROBE, "slash command was not registered")
printed = {}
local lines = SlashCmdList.IKPROBE()
assertTrue(type(lines) == "table" and #lines > 0, "probe returned no lines")
local text = joined() .. "\n" .. table.concat(lines, "\n")

assertTrue(text:find("GetGuildRosterInfo = function", 1, true), "roster function was not reported")
assertTrue(text:find("GuildRoster = function (present, not called)", 1, true), "GuildRoster was not kept uncalled")
assertTrue(text:find("IsInGuild returns", 1, true), "guild membership was not reported")
assertTrue(text:find("text=[Herberg]", 1, true), "guild name was not shown")
assertTrue(text:find("Scanned 3 of 3", 1, true), "the bounded scan did not cover the reported count")
assertTrue(text:find("roster index 2", 1, true), "the player row was not found")
assertTrue(text:find("Boolean field #9: true 2, false 1", 1, true), "offline boolean was not counted")
assertTrue(text:find("matches UnitName", 1, true), "the name field was not identified")
assertTrue(text:find("matches your level", 1, true), "the level field was not identified")
assertTrue(text:find("matches your localized class", 1, true), "the class field was not identified")
assertTrue(text:find("matches your character id", 1, true), "the id field was not identified")
assertTrue(text:find("matches the guild rank from GetGuildInfo", 1, true), "the rank field was not identified")
assertTrue(not text:find("Ada", 1, true), "a character name was printed")
assertTrue(not text:find("Bram", 1, true), "another character name was printed")
assertTrue(not text:find("Stormwind", 1, true), "a zone was printed")
assertTrue(not text:find("public note", 1, true), "a note was printed")
assertTrue(not text:find("Player-5826", 1, true), "a character id was printed")

local eventFrame
for i = 1, #frames do
	if frames[i]._scripts.OnEvent then eventFrame = frames[i] end
end
assertTrue(eventFrame and eventFrame._events.GUILD_ROSTER_UPDATE, "the roster event was not registered")
printed = {}
eventFrame._scripts.OnEvent(eventFrame, "GUILD_ROSTER_UPDATE", true)
local again = SlashCmdList.IKPROBE()
local second = table.concat(again, "\n")
assertTrue(second:find("Received 1 time", 1, true), "the roster event was not counted")
assertTrue(second:find("boolean true", 1, true), "the event argument was not described")

-- A client with none of the guild functions must still be able to run the command.
for name, _ in pairs({
	IsInGuild = true, GetGuildInfo = true, GetNumGuildMembers = true,
	GetGuildRosterInfo = true, GetGuildRosterLastOnline = true, UnitName = true,
	UnitFullName = true, UnitClass = true, UnitLevel = true, UnitGUID = true,
}) do
	_G[name] = nil
end
printed = {}
local bare = SlashCmdList.IKPROBE()
local bareText = table.concat(bare, "\n")
assertTrue(bareText:find("GetGuildRosterInfo = nil", 1, true), "a missing roster function was not reported")
assertTrue(bareText:find("was not called", 1, true), "missing functions were still called")
assertTrue(bareText:find("GetGuildRosterInfo was not called", 1, true), "a missing roster function was still called")

io.write("ok\n")
