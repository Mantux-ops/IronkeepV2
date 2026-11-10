-- Temporary read-only check. It does not write IronkeepRosterDB, does not
-- request a roster refresh, and has no SavedVariables.
-- /ikrosterdiff prints the result. Remove this addon when the check is done.
--
-- sameRoster matches addon/IronkeepRoster/Roster.lua from PR #62
-- (210c7ae): guild name, sequence length, then sorted lines of
-- guid, name, level, classToken, className, rankName.

IronkeepRosterDiag = IronkeepRosterDiag or {}

local DETAIL_CAP = 12
local READ_CAP = 500

local function say(text)
	if type(print) == "function" then
		print("|cff2dd4bfIronkeep diff|r " .. tostring(text))
	end
end

local function global(name)
	if type(_G) == "table" then return _G[name] end
	return nil
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

local function identityProblem(members)
	local guids, names = {}, {}
	local i
	for i = 1, #members do
		local member = members[i]
		if type(member) ~= "table" or type(member.guid) ~= "string" or member.guid == "" then return "missing-guid" end
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

local function callList(fn, ...)
	local storage = { n = 0 }
	local args = { ... }
	local argc = select("#", ...)
	local ok = pcall(function()
		local function save(...)
			storage.n = select("#", ...)
			local i
			for i = 1, storage.n do storage[i] = select(i, ...) end
		end
		if argc == 0 then
			save(fn())
		else
			save(fn(args[1]))
		end
	end)
	if not ok then return false end
	return true, storage
end

local function hasValue(storage)
	local i
	for i = 1, storage.n do
		if storage[i] ~= nil then return true end
	end
	return false
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

local function memberLine(member)
	if type(member) ~= "table" then return "" end
	return table.concat({
		tostring(member.guid),
		tostring(member.name),
		tostring(member.level),
		tostring(member.classToken),
		tostring(member.className),
		tostring(member.rankName),
	}, "\0")
end

-- Exact PR #62 rule. A true result is the only case that does not replace the snapshot.
local function sameRoster(previous, guild, members)
	if type(previous) ~= "table" or previous.wowGuildName ~= guild then return false end
	if type(previous.members) ~= "table" or #previous.members ~= #members then return false end
	local oldLines, newLines = {}, {}
	local i
	for i = 1, #members do
		oldLines[i] = memberLine(previous.members[i])
		newLines[i] = memberLine(members[i])
	end
	table.sort(oldLines)
	table.sort(newLines)
	for i = 1, #members do
		if oldLines[i] ~= newLines[i] then return false end
	end
	return true
end

local function guidText(member)
	if type(member) ~= "table" then return nil end
	if type(member.guid) ~= "string" or member.guid == "" then return nil end
	return member.guid
end

local function remember(bucket, member, duplicates)
	local guid = guidText(member)
	if not guid then return false end
	if bucket[guid] then
		duplicates.count = duplicates.count + 1
		return true
	end
	bucket[guid] = member
	return true
end

local function inspectSaved(db)
	local info = {
		walk = 0,
		hash = 0,
		extra = 0,
		missingGuid = 0,
		byGuid = {},
	}
	local duplicates = { count = 0 }
	if type(db) ~= "table" or type(db.members) ~= "table" then return info, duplicates.count end
	local members = db.members
	info.hash = #members
	local indexed = {}
	local i
	for i = 1, READ_CAP do
		if members[i] == nil then break end
		indexed[i] = true
		info.walk = info.walk + 1
		if not remember(info.byGuid, members[i], duplicates) then
			info.missingGuid = info.missingGuid + 1
		end
	end
	for key, value in pairs(members) do
		if not indexed[key] then
			info.extra = info.extra + 1
			if type(value) == "table" and not remember(info.byGuid, value, duplicates) then
				info.missingGuid = info.missingGuid + 1
			end
		end
	end
	return info, duplicates.count
end

local function readLive()
	local info = {
		rows = {},
		byGuid = {},
		empty = 0,
		errors = 0,
		missingGuid = 0,
		duplicates = 0,
		total = nil,
		online = nil,
		guild = nil,
		rank = nil,
		api = nil,
	}
	local countFn = global("GetNumGuildMembers")
	local rowFn = global("GetGuildRosterInfo")
	local infoFn = global("GetGuildInfo")
	if type(countFn) ~= "function" or type(rowFn) ~= "function" or type(infoFn) ~= "function" then
		info.api = "missing"
		return info
	end
	local countOk, counts = callList(countFn)
	if not countOk then
		info.api = "error"
		return info
	end
	info.total = counts[1]
	info.online = counts[2]
	local guildOk, guildStorage = callList(infoFn, "player")
	if guildOk then info.guild, info.rank = guildIdentity(guildStorage, playerHints()) end
	if type(info.total) ~= "number" or info.total < 1 then return info end
	local limit = info.total
	if limit > READ_CAP then limit = READ_CAP end
	local duplicates = { count = 0 }
	local index
	for index = 1, limit do
		local rowOk, row = callList(rowFn, index)
		if not rowOk then
			info.errors = info.errors + 1
		elseif not hasValue(row) then
			info.empty = info.empty + 1
		else
			local member = memberFrom(row)
			info.rows[#info.rows + 1] = member
			if not remember(info.byGuid, member, duplicates) then
				info.missingGuid = info.missingGuid + 1
			end
		end
	end
	info.duplicates = duplicates.count
	return info
end

local FIELDS = {
	{ key = "name", label = "name" },
	{ key = "level", label = "level" },
	{ key = "rankName", label = "rank" },
	{ key = "classToken", label = "class token" },
	{ key = "className", label = "class" },
}

local function diffPeople(savedInfo, live)
	local added, removed, changed = {}, {}, {}
	local guid, member
	for guid, member in pairs(savedInfo.byGuid) do
		if not live.byGuid[guid] then
			removed[#removed + 1] = { guid = guid, name = member.name }
		end
	end
	for guid, member in pairs(live.byGuid) do
		local previous = savedInfo.byGuid[guid]
		if not previous then
			added[#added + 1] = { guid = guid, name = member.name }
		else
			local f
			for f = 1, #FIELDS do
				local field = FIELDS[f]
				local oldValue = previous[field.key]
				local newValue = member[field.key]
				if tostring(oldValue) ~= tostring(newValue) then
					changed[#changed + 1] = {
						guid = guid,
						field = field.label,
						old = oldValue,
						new = newValue,
					}
				end
			end
		end
	end
	local function byGuid(a, b)
		return tostring(a.guid) < tostring(b.guid)
	end
	table.sort(added, byGuid)
	table.sort(removed, byGuid)
	table.sort(changed, function(a, b)
		if a.guid == b.guid then return a.field < b.field end
		return tostring(a.guid) < tostring(b.guid)
	end)
	return added, removed, changed
end

function IronkeepRosterDiag.Compare()
	local saved = IronkeepRosterDB
	local savedInfo, savedDuplicates = inspectSaved(saved)
	local live = readLive()
	local added, removed, changed = diffPeople(savedInfo, live)
	local comparable = live.api == nil and type(live.total) == "number" and live.total >= 1 and live.total <= READ_CAP and live.empty == 0 and live.errors == 0 and #live.rows == live.total
	local blocked = nil
	if comparable then
		blocked = identityProblem(live.rows) or playerOk(live.rows, playerHints(), live.rank)
		if blocked then comparable = false end
	end
	local matched = false
	if comparable then
		matched = sameRoster(saved, live.guild, live.rows)
	end
	return {
		saved = saved,
		savedWalk = savedInfo.walk,
		savedHash = savedInfo.hash,
		savedExtra = savedInfo.extra,
		savedMissingGuid = savedInfo.missingGuid,
		savedDuplicates = savedDuplicates,
		liveRows = #live.rows,
		liveEmpty = live.empty,
		liveErrors = live.errors,
		liveTotal = live.total,
		liveMissingGuid = live.missingGuid,
		liveDuplicates = live.duplicates,
		liveCapped = type(live.total) == "number" and live.total > READ_CAP,
		guildSaved = type(saved) == "table" and saved.wowGuildName or nil,
		guildLive = live.guild,
		api = live.api,
		blocked = blocked,
		comparable = comparable,
		sameRoster = matched,
		added = added,
		removed = removed,
		changed = changed,
		capturedAt = type(saved) == "table" and saved.capturedAt or nil,
	}
end

local function showSome(label, rows, formatRow)
	local shown = #rows
	if shown > DETAIL_CAP then shown = DETAIL_CAP end
	local i
	for i = 1, shown do
		say(label .. " " .. formatRow(rows[i]))
	end
	if #rows > DETAIL_CAP then
		say(label .. " " .. tostring(#rows - DETAIL_CAP) .. " more")
	end
end

function IronkeepRosterDiag.Report()
	local before = IronkeepRosterDB
	local result = IronkeepRosterDiag.Compare()
	say("capturedAt " .. tostring(result.capturedAt))
	say("saved walk " .. tostring(result.savedWalk) .. ", hash " .. tostring(result.savedHash) .. ", extra " .. tostring(result.savedExtra))
	say("live rows " .. tostring(result.liveRows) .. ", reported " .. tostring(result.liveTotal) .. ", empty " .. tostring(result.liveEmpty) .. ", errors " .. tostring(result.liveErrors))
	say("guild [" .. tostring(result.guildSaved) .. "] vs [" .. tostring(result.guildLive) .. "]")
	if result.api ~= nil then
		say("live roster API " .. tostring(result.api))
	end
	if result.liveCapped then
		say("live roster stopped at " .. tostring(READ_CAP))
	end
	if not result.comparable then
		say("sameRoster skipped (" .. tostring(result.blocked or result.api or "incomplete") .. ")")
	elseif result.sameRoster then
		say("sameRoster true")
	else
		say("sameRoster false")
	end
	say("added " .. tostring(#result.added) .. ", removed " .. tostring(#result.removed) .. ", changed " .. tostring(#result.changed))
	if result.savedMissingGuid > 0 or result.liveMissingGuid > 0 then
		say("missing guid saved " .. tostring(result.savedMissingGuid) .. ", live " .. tostring(result.liveMissingGuid))
	end
	if result.savedDuplicates > 0 or result.liveDuplicates > 0 then
		say("duplicate guid saved " .. tostring(result.savedDuplicates) .. ", live " .. tostring(result.liveDuplicates))
	end
	showSome("added", result.added, function(row)
		return tostring(row.guid) .. " " .. tostring(row.name)
	end)
	showSome("removed", result.removed, function(row)
		return tostring(row.guid) .. " " .. tostring(row.name)
	end)
	showSome("changed", result.changed, function(row)
		return tostring(row.guid) .. " " .. row.field .. " [" .. tostring(row.old) .. "] => [" .. tostring(row.new) .. "]"
	end)
	if before ~= IronkeepRosterDB then
		say("stopped because the saved snapshot pointer changed")
	end
	return result
end

SLASH_IKROSTERDIFF1 = "/ikrosterdiff"
if type(SlashCmdList) ~= "table" then SlashCmdList = {} end
SlashCmdList.IKROSTERDIFF = function()
	return IronkeepRosterDiag.Report()
end
