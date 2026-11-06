-- Development-only guild API probe for one WoW Forever client.
-- Read-only: it never invites, removes, promotes, edits notes, or requests a roster refresh.
-- It has no SavedVariables and does not write IronkeepDB.

IronkeepRosterProbe = IronkeepRosterProbe or {}

local SCAN_CAP = 200
local LINE_CAP = 80

local NEVER_CALL = {
	GuildRoster = true,
	GuildInvite = true,
	GuildUninvite = true,
	GuildLeave = true,
	GuildPromote = true,
	GuildDemote = true,
	GuildSetLeader = true,
	GuildSetMOTD = true,
	GuildRosterSetPublicNote = true,
	GuildRosterSetOfficerNote = true,
	SetGuildRosterShowOffline = true,
	SetGuildRosterSelection = true,
	GuildControlSetRank = true,
}

local EXISTS = {
	"IsInGuild",
	"GetGuildInfo",
	"GetNumGuildMembers",
	"GetGuildRosterInfo",
	"GetGuildRosterLastOnline",
	"GetGuildRosterSelection",
	"GetGuildRosterShowOffline",
	"CanViewOfficerNote",
	"CanEditPublicNote",
	"CanEditOfficerNote",
	"UnitIsInMyGuild",
	"UnitName",
	"UnitFullName",
	"UnitClass",
	"UnitLevel",
	"UnitGUID",
	"GuildRoster",
	"GuildInvite",
	"GuildUninvite",
	"GuildRosterSetPublicNote",
	"GuildRosterSetOfficerNote",
	"SetGuildRosterShowOffline",
}

local frame
local eventRegistered = false
local eventCount = 0
local eventArgs = "none"
local entered = false

local function global(name)
	if type(_G) == "table" then return _G[name] end
	return nil
end

local function invoke(fn, mode)
	if type(fn) ~= "function" then
		return false, "not a function"
	end
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
	if not ok then
		return false, err
	end
	return true, storage
end

local function hints()
	local found = {
		name = nil,
		fullFirst = nil,
		fullJoined = nil,
		classLocal = nil,
		classFile = nil,
		level = nil,
		guid = nil,
		guild = nil,
		rank = nil,
	}
	local nameFn = global("UnitName")
	if type(nameFn) == "function" then
		local ok, value = pcall(nameFn, "player")
		if ok and type(value) == "string" and value ~= "" then found.name = value end
	end
	local fullFn = global("UnitFullName")
	if type(fullFn) == "function" then
		local fullOk, first, second = pcall(fullFn, "player")
		if fullOk and type(first) == "string" and first ~= "" then
			found.fullFirst = first
			if type(second) == "string" and second ~= "" then
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

local function rememberGuild(found, storage)
	if not storage then return end
	local i
	for i = 1, storage.n do
		local value = storage[i]
		if type(value) == "string" and value ~= "" then
			if not found.guild then
				found.guild = value
			elseif not found.rank and value ~= found.guild then
				found.rank = value
			end
		end
	end
end

local function describe(value, found)
	local kind = type(value)
	if kind == "nil" then return "nil" end
	if kind == "boolean" then return "boolean " .. tostring(value) end
	if kind == "number" then
		local text = "number " .. tostring(value)
		if found and found.level ~= nil and value == found.level then
			text = text .. "; matches your level"
		end
		return text
	end
	if kind == "string" then
		local text = "string length " .. tostring(#value)
		if value == "" then return text .. "; empty" end
		if found then
			if found.name and value == found.name then
				return text .. "; matches UnitName"
			end
			if found.fullJoined and value == found.fullJoined then
				return text .. "; matches UnitFullName joined"
			end
			if found.fullFirst and value == found.fullFirst then
				return text .. "; matches the first UnitFullName value"
			end
			if found.guid and value == found.guid then
				return text .. "; matches your character id"
			end
			if found.classLocal and value == found.classLocal then
				return text .. "; matches your localized class"
			end
			if found.classFile and value == found.classFile then
				return text .. "; matches your class file token"
			end
			if found.guild and value == found.guild then
				return text .. "; matches the guild name from GetGuildInfo"
			end
			if found.rank and value == found.rank then
				return text .. "; matches the guild rank from GetGuildInfo"
			end
		end
		return text .. "; hidden"
	end
	return kind
end

local function failure(err, found)
	if type(err) ~= "string" then return "call failed (" .. type(err) .. ")" end
	local clean = err
	if found and found.name and found.name ~= "" then
		clean = string.gsub(clean, found.name, "[redacted]")
	end
	if #clean > 160 then clean = string.sub(clean, 1, 160) end
	return "call failed: " .. clean
end

local function add(lines, text)
	if #lines >= LINE_CAP then return end
	lines[#lines + 1] = text
	if type(print) == "function" then
		print("|cff2dd4bfIronkeep probe|r " .. text)
	end
end

local function queryIndex(index)
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

local function isPlayer(storage, found)
	local i
	for i = 1, storage.n do
		local value = storage[i]
		if found.name and value == found.name then return true end
		if found.fullJoined and value == found.fullJoined then return true end
		if found.fullFirst and value == found.fullFirst then return true end
	end
	return false
end

function IronkeepRosterProbe.Run()
	local lines = {}
	local found = hints()
	add(lines, "Development-only read-only check. No guild changes, no network request, nothing saved.")

	local i
	for i = 1, #EXISTS do
		local name = EXISTS[i]
		local value = global(name)
		local marker = "callable"
		if NEVER_CALL[name] then marker = "present, not called" end
		add(lines, name .. " = " .. type(value) .. (type(value) == "function" and (" (" .. marker .. ")") or ""))
	end

	local inGuild = global("IsInGuild")
	local ok, result = invoke(inGuild, "none")
	if type(inGuild) ~= "function" then
		add(lines, "IsInGuild was not called.")
	elseif not ok then
		add(lines, "IsInGuild " .. failure(result, found))
	else
		add(lines, "IsInGuild returns " .. tostring(result.n) .. " value(s): " .. describe(result[1], found))
	end

	local info = global("GetGuildInfo")
	ok, result = invoke(info, "player")
	if type(info) ~= "function" then
		add(lines, "GetGuildInfo was not called.")
	elseif not ok then
		add(lines, "GetGuildInfo " .. failure(result, found))
	else
		rememberGuild(found, result)
		add(lines, "GetGuildInfo(\"player\") returns " .. tostring(result.n) .. " value(s).")
		for i = 1, result.n do
			local value = result[i]
			if type(value) == "string" and #value > 0 and #value <= 40 then
				add(lines, "  guild info #" .. tostring(i) .. " = " .. describe(value, found) .. " text=[" .. value .. "]")
			else
				add(lines, "  guild info #" .. tostring(i) .. " = " .. describe(value, found))
			end
		end
	end

	local countFn = global("GetNumGuildMembers")
	local total, second
	ok, result = invoke(countFn, "none")
	if type(countFn) ~= "function" then
		add(lines, "GetNumGuildMembers was not called.")
	elseif not ok then
		add(lines, "GetNumGuildMembers " .. failure(result, found))
	else
		add(lines, "GetNumGuildMembers returns " .. tostring(result.n) .. " value(s).")
		for i = 1, result.n do
			add(lines, "  count #" .. tostring(i) .. " = " .. describe(result[i], found))
		end
		if type(result[1]) == "number" then total = result[1] end
		if type(result[2]) == "number" then second = result[2] end
		if total and second then
			add(lines, "The two numbers are not labeled by this client. Compare them with the guild window.")
		end
	end

	local rosterFn = global("GetGuildRosterInfo")
	if type(rosterFn) ~= "function" then
		add(lines, "GetGuildRosterInfo was not called.")
	elseif type(total) ~= "number" or total < 1 then
		add(lines, "GetGuildRosterInfo was not scanned because the count is missing or zero.")
		add(lines, "GuildRoster() was not called. If the guild window fills a local cache, open it and run /ikprobe again.")
	else
		local limit = total
		if limit > SCAN_CAP then limit = SCAN_CAP end
		local queried, populated, playerAt = 0, 0, nil
		local boolTrue, boolFalse = {}, {}
		local maxSlots = 0
		local sample, sampleIndex
		for i = 1, limit do
			local rowOk, row = queryIndex(i)
			queried = queried + 1
			if rowOk and hasValue(row) then
				populated = populated + 1
				if row.n > maxSlots then maxSlots = row.n end
				local slot
				for slot = 1, row.n do
					local value = row[slot]
					if type(value) == "boolean" then
						if value then boolTrue[slot] = (boolTrue[slot] or 0) + 1
						else boolFalse[slot] = (boolFalse[slot] or 0) + 1 end
					end
				end
				if isPlayer(row, found) then
					playerAt = i
					sample = row
					sampleIndex = i
				elseif not sample then
					sample = row
					sampleIndex = i
				end
			elseif not rowOk then
				add(lines, "GetGuildRosterInfo(" .. tostring(i) .. ") " .. failure(row, found))
				break
			end
		end
		add(lines, "Scanned " .. tostring(queried) .. " of " .. tostring(total) .. " reported members; " .. tostring(populated) .. " had a value. Cap is " .. tostring(SCAN_CAP) .. ".")
		if populated == 0 then
			add(lines, "The count was non-zero but every scanned call returned only nil. GuildRoster() was not called.")
		end
		if playerAt then
			add(lines, "Your character was found at roster index " .. tostring(playerAt) .. " without printing the name.")
		else
			add(lines, "No scanned row matched your character name. The sample is the first populated row.")
		end
		local sawFalse = false
		local slot
		for slot = 1, maxSlots do
			local yes = boolTrue[slot] or 0
			local no = boolFalse[slot] or 0
			if yes + no > 0 then
				add(lines, "Boolean field #" .. tostring(slot) .. ": true " .. tostring(yes) .. ", false " .. tostring(no) .. ".")
				if no > 0 then sawFalse = true end
			end
		end
		if sawFalse then
			add(lines, "At least one boolean is false for a row GetGuildRosterInfo returned. Compare that field with online status in the guild window.")
		else
			add(lines, "No returned boolean was false. That does not prove offline members are missing.")
		end
		if sample then
			add(lines, "Sample row " .. tostring(sampleIndex) .. " has " .. tostring(sample.n) .. " return(s). Strings that are not your identity stay hidden.")
			for slot = 1, sample.n do
				add(lines, "  field #" .. tostring(slot) .. " = " .. describe(sample[slot], found))
			end
		end
		local lastOnline = global("GetGuildRosterLastOnline")
		if type(lastOnline) == "function" and sampleIndex then
			local when = { n = 0 }
			local whenOk, whenErr = pcall(function()
				local function save(...)
					when.n = select("#", ...)
					local n
					for n = 1, when.n do when[n] = select(n, ...) end
				end
				save(lastOnline(sampleIndex))
			end)
			if not whenOk then
				add(lines, "GetGuildRosterLastOnline " .. failure(whenErr, found))
			else
				add(lines, "GetGuildRosterLastOnline(sample) returns " .. tostring(when.n) .. " value(s).")
				for slot = 1, when.n do
					add(lines, "  last online #" .. tostring(slot) .. " = " .. describe(when[slot], found))
				end
			end
		end
	end

	if eventRegistered then
		add(lines, "GUILD_ROSTER_UPDATE registration succeeded. Received " .. tostring(eventCount) .. " time(s). Last arguments: " .. eventArgs)
	else
		add(lines, "GUILD_ROSTER_UPDATE could not be registered. The client may not provide that event.")
	end
	return lines
end

local function onEvent(_, event, ...)
	if event == "GUILD_ROSTER_UPDATE" then
		eventCount = eventCount + 1
		local n = select("#", ...)
		local parts = {}
		local i
		for i = 1, n do
			parts[#parts + 1] = describe(select(i, ...), nil)
		end
		eventArgs = n == 0 and "no arguments" or table.concat(parts, ", ")
		return
	end
	if event == "PLAYER_ENTERING_WORLD" and not entered then
		entered = true
		IronkeepRosterProbe.Run()
	end
end

if type(CreateFrame) == "function" then
	local ok, created = pcall(CreateFrame, "Frame")
	if ok and created then
		frame = created
		if type(frame.SetScript) == "function" then
			pcall(frame.SetScript, frame, "OnEvent", onEvent)
		end
		if type(frame.RegisterEvent) == "function" then
			local registered = pcall(frame.RegisterEvent, frame, "GUILD_ROSTER_UPDATE")
			eventRegistered = registered and true or false
			pcall(frame.RegisterEvent, frame, "PLAYER_ENTERING_WORLD")
		end
	end
end

SLASH_IKPROBE1 = "/ikprobe"
if type(SlashCmdList) ~= "table" then SlashCmdList = {} end
SlashCmdList.IKPROBE = function()
	return IronkeepRosterProbe.Run()
end

if type(print) == "function" then
	print("|cff2dd4bfIronkeep probe|r loaded. Type /ikprobe for the read-only guild check.")
end
