-- Guild roster snapshot for one WoW Forever client.
-- A scan is published only when it is complete and every character name and
-- GUID is present and unique. Any other result leaves IronkeepRosterDB as it was.
-- This file does not read or write IronkeepDB.
--
-- Field positions were checked on one Forever client (guild Herberg, 214 members):
-- 1 name, 2 rank name, 4 level, 5 localized class, 11 class file token, 17 GUID.
-- Rank index and per-character online status are not stored.

Ironkeep = Ironkeep or {}
Ironkeep.Roster = {}

local SCAN_CAP = 500
Ironkeep.Roster.SCAN_CAP = SCAN_CAP

local function global(name)
	if type(_G) == "table" then return _G[name] end
	return nil
end

local function say(text)
	if type(Ironkeep.Print) == "function" then
		Ironkeep.Print(text)
		return
	end
	if type(print) == "function" then
		print("|cff2dd4bfIronkeep|r " .. tostring(text))
	end
end

local function wholeNumber(value)
	return type(value) == "number" and value >= 0 and value < 1000000000 and value == math.floor(value)
end

local function callReturns(fn, mode)
	if type(fn) ~= "function" then return false, "not a function" end
	local storage = { n = 0 }
	local ok, err = pcall(function()
		local function save(...)
			storage.n = select("#", ...)
			local i
			for i = 1, storage.n do
				storage[i] = select(i, ...)
			end
		end
		if mode == "player" then
			save(fn("player"))
		else
			save(fn())
		end
	end)
	if not ok then return false, err end
	return true, storage
end

local function rosterRow(index)
	local fn = global("GetGuildRosterInfo")
	if type(fn) ~= "function" then return false, "not a function" end
	local storage = { n = 0 }
	local ok, err = pcall(function()
		local function save(...)
			storage.n = select("#", ...)
			local i
			for i = 1, storage.n do
				storage[i] = select(i, ...)
			end
		end
		save(fn(index))
	end)
	if not ok then return false, err end
	return true, storage
end

local function hasValue(storage)
	local i
	for i = 1, storage.n do
		if storage[i] ~= nil then return true end
	end
	return false
end

local function countKey(storage)
	if not storage then return "missing" end
	return tostring(storage.n) .. ":" .. tostring(storage[1]) .. ":" .. tostring(storage[2])
end

local function playerHints()
	local found = {}
	local nameFn = global("UnitName")
	if type(nameFn) == "function" then
		local ok, value = pcall(nameFn, "player")
		if ok and type(value) == "string" and string.find(value, "%S") then found.name = value end
	end
	local fullFn = global("UnitFullName")
	if type(fullFn) == "function" then
		local ok, first, second = pcall(fullFn, "player")
		if ok and type(first) == "string" and string.find(first, "%S") then
			found.fullFirst = first
			if type(second) == "string" and string.find(second, "%S") then
				found.fullJoined = first .. " " .. second
			end
		end
	end
	local classFn = global("UnitClass")
	if type(classFn) == "function" then
		local ok, localName, file = pcall(classFn, "player")
		if ok then
			if type(localName) == "string" and localName ~= "" then found.classLocal = localName end
			if type(file) == "string" and file ~= "" then found.classFile = file end
		end
	end
	local levelFn = global("UnitLevel")
	if type(levelFn) == "function" then
		local ok, value = pcall(levelFn, "player")
		if ok and type(value) == "number" then found.level = value end
	end
	local guidFn = global("UnitGUID")
	if type(guidFn) == "function" then
		local ok, value = pcall(guidFn, "player")
		if ok and type(value) == "string" and value ~= "" then found.guid = value end
	end
	return found
end

local function isPlayerText(value, found)
	if type(value) ~= "string" or value == "" then return false end
	if found.name and value == found.name then return true end
	if found.fullJoined and value == found.fullJoined then return true end
	if found.fullFirst and value == found.fullFirst then return true end
	if found.guid and value == found.guid then return true end
	return false
end

local function guildIdentity(storage, found)
	local guild, rank
	local i
	for i = 1, storage.n do
		local value = storage[i]
		if type(value) == "string" and value ~= "" and not isPlayerText(value, found) then
			if not guild then
				guild = value
			elseif not rank and value ~= guild then
				rank = value
			end
		end
	end
	return guild, rank
end

local function nameMatches(name, found)
	if type(name) ~= "string" then return false end
	if found.name and name == found.name then return true end
	if found.fullJoined and name == found.fullJoined then return true end
	if found.fullFirst and name == found.fullFirst then return true end
	return false
end

local function presentText(value)
	return type(value) == "string" and string.find(value, "%S") ~= nil
end

local function memberFrom(storage)
	return {
		guid = storage[17],
		name = storage[1],
		level = storage[4],
		classToken = storage[11],
		className = storage[5],
		rankName = storage[2],
	}
end

local function identityProblem(members)
	local guids = {}
	local names = {}
	local i
	for i = 1, #members do
		local member = members[i]
		if type(member.guid) ~= "string" or member.guid == "" then return "missing-guid" end
		if not presentText(member.name) then return "missing-name" end
		if type(member.level) ~= "number" then return "invalid-member" end
		if not presentText(member.classToken) or not presentText(member.className) or not presentText(member.rankName) then
			return "invalid-member"
		end
		if guids[member.guid] then return "duplicate-guid" end
		if names[member.name] then return "duplicate-name" end
		guids[member.guid] = true
		names[member.name] = true
	end
	return nil
end

local function playerOk(members, found, rank)
	if not found.guid or not nameMatches(found.name or found.fullJoined or found.fullFirst, found) then
		return "player-check-failed"
	end
	if type(found.level) ~= "number" or not presentText(found.classFile) or not presentText(found.classLocal) or not presentText(rank) then
		return "player-check-failed"
	end
	local i
	for i = 1, #members do
		local member = members[i]
		if member.guid == found.guid then
			if not nameMatches(member.name, found) then return "player-check-failed" end
			if member.level ~= found.level then return "player-check-failed" end
			if member.classToken ~= found.classFile then return "player-check-failed" end
			if member.className ~= found.classLocal then return "player-check-failed" end
			if member.rankName ~= rank then return "player-check-failed" end
			return nil
		end
	end
	return "player-not-found"
end

local function captureTime()
	local fn = global("time")
	if type(fn) ~= "function" then return nil end
	local ok, value = pcall(fn)
	if ok and type(value) == "number" then return value end
	return nil
end

local function result(reason, examined, populated, empty, errors, total, online, stable)
	return {
		published = false,
		reason = reason,
		examined = examined or 0,
		populated = populated or 0,
		empty = empty or 0,
		errors = errors or 0,
		reportedTotal = total,
		reportedOnline = online,
		countStable = stable and true or false,
	}
end

local function announce(info, guild)
	if info.published then
		say("Guild roster saved. " .. tostring(info.populated) .. " members for " .. tostring(guild) .. ".")
		return
	end
	say("Guild roster was not saved (" .. tostring(info.reason) .. "). The previous snapshot is unchanged.")
end

function Ironkeep.Roster.Scan()
	local found = playerHints()
	local inFn = global("IsInGuild")
	if type(inFn) == "function" then
		local ok, value = pcall(inFn)
		if not ok or not value then
			local info = result("not-in-guild", 0, 0, 0, 0, nil, nil, false)
			announce(info)
			return info
		end
	end

	local infoFn = global("GetGuildInfo")
	if type(infoFn) ~= "function" or type(global("GetNumGuildMembers")) ~= "function" or type(global("GetGuildRosterInfo")) ~= "function" then
		local info = result("missing-api", 0, 0, 0, 0, nil, nil, false)
		announce(info)
		return info
	end

	local infoOk, guildStorage = callReturns(infoFn, "player")
	if not infoOk then
		local info = result("api-error", 0, 0, 0, 1, nil, nil, false)
		announce(info)
		return info
	end
	local guild, rank = guildIdentity(guildStorage, found)
	if not guild then
		local info = result("no-guild-name", 0, 0, 0, 0, nil, nil, false)
		announce(info)
		return info
	end

	local countOk, counts = callReturns(global("GetNumGuildMembers"), "none")
	if not countOk then
		local info = result("api-error", 0, 0, 0, 1, nil, nil, false)
		announce(info)
		return info
	end
	local total = counts[1]
	local online = counts[2]
	if not wholeNumber(total) or type(online) ~= "number" then
		local info = result("count-shape", 0, 0, 0, 0, total, online, false)
		announce(info)
		return info
	end
	if total < 1 then
		local info = result("empty", 0, 0, 0, 0, total, online, true)
		announce(info)
		return info
	end

	local firstKey = countKey(counts)
	local limit = total
	local capped = false
	if limit > SCAN_CAP then
		limit = SCAN_CAP
		capped = true
	end

	local members = {}
	local examined, populated, empty, errors = 0, 0, 0, 0
	local i
	for i = 1, limit do
		if i > 1 and (i - 1) % 100 == 0 then
			local againOk, again = callReturns(global("GetNumGuildMembers"), "none")
			if not againOk or countKey(again) ~= firstKey then
				local info = result("count-changed", examined, populated, empty, errors, total, online, false)
				announce(info)
				return info
			end
		end
		local rowOk, row = rosterRow(i)
		examined = examined + 1
		if not rowOk then
			errors = errors + 1
			local info = result("api-error", examined, populated, empty, errors, total, online, true)
			announce(info)
			return info
		end
		if hasValue(row) then
			populated = populated + 1
			members[#members + 1] = memberFrom(row)
		else
			empty = empty + 1
		end
	end

	local endOk, ended = callReturns(global("GetNumGuildMembers"), "none")
	if not endOk or countKey(ended) ~= firstKey then
		local info = result("count-changed", examined, populated, empty, errors, total, online, false)
		announce(info)
		return info
	end
	if capped or examined ~= total or populated ~= total or empty ~= 0 or errors ~= 0 then
		local reason = capped and "partial-cap" or "incomplete"
		local info = result(reason, examined, populated, empty, errors, total, online, true)
		announce(info)
		return info
	end

	local problem = identityProblem(members)
	if problem then
		local info = result(problem, examined, populated, empty, errors, total, online, true)
		announce(info)
		return info
	end
	problem = playerOk(members, found, rank)
	if problem then
		local info = result(problem, examined, populated, empty, errors, total, online, true)
		announce(info)
		return info
	end

	local capturedAt = captureTime()
	if capturedAt == nil then
		local info = result("no-capture-time", examined, populated, empty, errors, total, online, true)
		announce(info)
		return info
	end

	-- Publish by replacing the global. The previous table is left untouched.
	IronkeepRosterDB = {
		schema = 1,
		wowGuildName = guild,
		capturedAt = capturedAt,
		completeness = {
			status = "complete",
			examined = examined,
			populated = populated,
			empty = empty,
			errors = errors,
			reportedTotal = total,
			reportedOnline = online,
			countStable = true,
		},
		playerChecks = {
			nameField = 1,
			rankNameField = 2,
			levelField = 4,
			classNameField = 5,
			classTokenField = 11,
			guidField = 17,
		},
		members = members,
	}
	local info = result("published", examined, populated, empty, errors, total, online, true)
	info.published = true
	announce(info, guild)
	return info
end

SLASH_IKROSTER1 = "/ikroster"
if type(SlashCmdList) ~= "table" then SlashCmdList = {} end
SlashCmdList.IKROSTER = function()
	return Ironkeep.Roster.Scan()
end
