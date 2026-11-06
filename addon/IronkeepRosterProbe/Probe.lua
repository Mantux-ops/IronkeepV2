-- Development-only guild API probe for one WoW Forever client.
-- Read-only: it never invites, removes, promotes, edits notes, or requests a roster refresh.
-- It has no SavedVariables and does not write IronkeepDB.
--
-- Safety cap: one command examines at most 500 roster indexes.
-- The first Forever test stopped at 200 because of the old probe, not the client.
-- A scan that hits this cap, hits an API error, or sees the member count change
-- is reported as partial. Field positions are not given fixed meanings.

IronkeepRosterProbe = IronkeepRosterProbe or {}

local SCAN_CAP = 500
local LINE_CAP = 80
local FIELD_LINE_CAP = 40
IronkeepRosterProbe.SCAN_CAP = SCAN_CAP

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

local TYPE_ORDER = {
	"nil", "boolean", "number", "string", "table", "function", "thread", "userdata",
}

local frame
local eventRegistered = false
local eventCount = 0
local eventArgs = "none"
local eventMark = 0
local entered = false

local function global(name)
	if type(_G) == "table" then return _G[name] end
	return nil
end

local function add(lines, text)
	if lines.truncated then return end
	if #lines >= LINE_CAP - 1 then
		lines.truncated = true
		lines[#lines + 1] = "Output stopped at " .. tostring(LINE_CAP) .. " lines."
		if type(print) == "function" then
			print("|cff2dd4bfIronkeep probe|r Output stopped at " .. tostring(LINE_CAP) .. " lines.")
		end
		return
	end
	lines[#lines + 1] = text
	if type(print) == "function" then
		print("|cff2dd4bfIronkeep probe|r " .. text)
	end
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
	if not ok then return false, err end
	return true, storage
end

local function hints()
	local found = {}
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

local function redact(text, secret)
	if type(secret) ~= "string" or secret == "" then return text end
	local out = ""
	local start = 1
	while true do
		local from, to = string.find(text, secret, start, true)
		if not from then return out .. string.sub(text, start) end
		out = out .. string.sub(text, start, from - 1) .. "[redacted]"
		start = to + 1
	end
end

local function failure(err, found)
	if type(err) ~= "string" then return "call failed (" .. type(err) .. ")" end
	local clean = err
	if found then
		clean = redact(clean, found.fullJoined)
		clean = redact(clean, found.name)
		clean = redact(clean, found.fullFirst)
		clean = redact(clean, found.guid)
	end
	if #clean > 160 then clean = string.sub(clean, 1, 160) end
	return "call failed: " .. clean
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

local function wholeNumber(value)
	return type(value) == "number" and value >= 0 and value < 1000000000 and value == math.floor(value)
end

local function countKey(storage)
	if not storage then return "missing" end
	return tostring(storage.n) .. ":" .. tostring(storage[1]) .. ":" .. tostring(storage[2])
end

local function readCounts()
	local fn = global("GetNumGuildMembers")
	if type(fn) ~= "function" then return false, "not a function" end
	return invoke(fn, "none")
end

local function copyRow(row)
	local copy = { n = row.n }
	local i
	for i = 1, row.n do copy[i] = row[i] end
	return copy
end

local function playerScore(row, found)
	local guidHit, nameHit = false, false
	local i
	for i = 1, row.n do
		local value = row[i]
		if found.guid and value == found.guid then guidHit = true end
		if found.name and value == found.name then nameHit = true end
		if found.fullJoined and value == found.fullJoined then nameHit = true end
		if found.fullFirst and value == found.fullFirst then nameHit = true end
	end
	if guidHit then return 2 end
	if nameHit then return 1 end
	return 0
end

local function tagsFor(value, found)
	local tags = {}
	if type(value) == "number" and found.level ~= nil and value == found.level then
		tags[#tags + 1] = "equals your level"
	end
	if type(value) ~= "string" or value == "" then return tags end
	if found.name and value == found.name then tags[#tags + 1] = "matches UnitName" end
	if found.fullJoined and value == found.fullJoined then tags[#tags + 1] = "matches UnitFullName joined" end
	if found.fullFirst and value == found.fullFirst then tags[#tags + 1] = "matches the first UnitFullName value" end
	if found.guid and value == found.guid then tags[#tags + 1] = "matches your character id" end
	if found.classLocal and value == found.classLocal then tags[#tags + 1] = "matches your localized class" end
	if found.classFile and value == found.classFile then tags[#tags + 1] = "matches your class file token" end
	if found.guild and value == found.guild then tags[#tags + 1] = "matches the guild name from GetGuildInfo" end
	if found.rank and value == found.rank then tags[#tags + 1] = "matches the guild rank from GetGuildInfo" end
	return tags
end

local function newSlot()
	return {
		present = 0,
		nils = 0,
		types = {},
		boolTrue = 0,
		boolFalse = 0,
		numMin = nil,
		numMax = nil,
		lenMin = nil,
		lenMax = nil,
		emptyStr = 0,
		playerTags = {},
	}
end

local function recordValue(slot, value)
	slot.present = slot.present + 1
	local kind = type(value)
	slot.types[kind] = (slot.types[kind] or 0) + 1
	if value == nil then
		slot.nils = slot.nils + 1
		return
	end
	if kind == "boolean" then
		if value then slot.boolTrue = slot.boolTrue + 1
		else slot.boolFalse = slot.boolFalse + 1 end
	elseif kind == "number" then
		if slot.numMin == nil or value < slot.numMin then slot.numMin = value end
		if slot.numMax == nil or value > slot.numMax then slot.numMax = value end
	elseif kind == "string" then
		if value == "" then
			slot.emptyStr = slot.emptyStr + 1
		else
			local length = #value
			if slot.lenMin == nil or length < slot.lenMin then slot.lenMin = length end
			if slot.lenMax == nil or length > slot.lenMax then slot.lenMax = length end
		end
	end
end

local function firstEqual(row, expected)
	if row == nil or expected == nil or expected == "" then return nil end
	local i
	for i = 1, row.n do
		if row[i] == expected then return i end
	end
	return nil
end

local function tally(list)
	local seen = {}
	local values, extras = 0, 0
	local i
	for i = 1, #list do
		local key = list[i]
		seen[key] = (seen[key] or 0) + 1
	end
	for _, count in pairs(seen) do
		if count > 1 then
			values = values + 1
			extras = extras + (count - 1)
		end
	end
	for i = 1, #list do list[i] = nil end
	return values, extras
end

local function noteCounts(scan)
	local ok, storage = readCounts()
	if not ok then
		if scan.countKey == nil then
			scan.countError = storage
			return
		end
		scan.countChanged = true
		scan.countRereadFailed = true
		return
	end
	local key = countKey(storage)
	if scan.countKey == nil then
		scan.countKey = key
		scan.counts = storage
		if wholeNumber(storage[1]) then scan.total = storage[1] end
		if type(storage[2]) == "number" then scan.second = storage[2] end
		return
	end
	if key ~= scan.countKey then
		scan.countChanged = true
		scan.laterCounts = storage
	end
end

local function finishStatus(scan)
	scan.reasons = {}
	if scan.capped then scan.reasons[#scan.reasons + 1] = "safety cap" end
	if scan.errors > 0 then scan.reasons[#scan.reasons + 1] = "API errors" end
	if scan.countChanged then scan.reasons[#scan.reasons + 1] = "member count changed" end
	if scan.reasons[1] then scan.status = "partial"
	else scan.status = "complete" end
end

local function identityOf(row, found)
	local nameField = firstEqual(row, found.name)
	if not nameField then nameField = firstEqual(row, found.fullJoined) end
	if not nameField then nameField = firstEqual(row, found.fullFirst) end
	return nameField, firstEqual(row, found.guid)
end

local function classifyIdentity(scan)
	local nameField, guidField = identityOf(scan.playerRow, scan.found)
	scan.nameField = nameField
	scan.guidField = guidField
	local slot
	for slot = 1, scan.playerRow.n do
		local tags = tagsFor(scan.playerRow[slot], scan.found)
		local stats = scan.slots[slot]
		if stats and tags[1] then stats.playerTags = tags end
	end
	scan.playerRow = nil
	if not nameField and not guidField then
		scan.identityNote = "No scanned row value matched UnitName, UnitFullName, or UnitGUID."
		return
	end
	local names, guids = {}, {}
	local nameNon, nameMissing, nameOther = 0, 0, 0
	local guidNon, guidMissing, guidOther = 0, 0, 0
	local i
	for i = 1, scan.examined do
		local ok, row = queryIndex(i)
		if not ok then
			scan.identityErrors = (scan.identityErrors or 0) + 1
		elseif hasValue(row) then
			if nameField then
				local value = nameField <= row.n and row[nameField] or nil
				if type(value) == "string" and value ~= "" then
					nameNon = nameNon + 1
					names[#names + 1] = value
				elseif value == nil or value == "" then
					nameMissing = nameMissing + 1
				else
					nameOther = nameOther + 1
				end
			end
			if guidField then
				local value = guidField <= row.n and row[guidField] or nil
				if type(value) == "string" and value ~= "" then
					guidNon = guidNon + 1
					guids[#guids + 1] = value
				elseif value == nil or value == "" then
					guidMissing = guidMissing + 1
				else
					guidOther = guidOther + 1
				end
			end
		end
	end
	if nameField then
		local dup, extra = tally(names)
		scan.nameNon, scan.nameMissing, scan.nameOther = nameNon, nameMissing, nameOther
		scan.nameDup, scan.nameExtra = dup, extra
	end
	if guidField then
		local dup, extra = tally(guids)
		scan.guidNon, scan.guidMissing, scan.guidOther = guidNon, guidMissing, guidOther
		scan.guidDup, scan.guidExtra = dup, extra
	end
end

local function onlineCandidates(scan)
	scan.candidates = {}
	if scan.status ~= "complete" then return end
	if type(scan.total) ~= "number" or type(scan.second) ~= "number" then return end
	local slot
	for slot = 1, scan.widest do
		local stats = scan.slots[slot]
		if stats then
			local yes, no = stats.boolTrue, stats.boolFalse
			local remainder = scan.total - scan.second
			if yes + no == scan.total and yes == scan.second and no == remainder then
				scan.candidates[#scan.candidates + 1] = {
					slot = slot, yes = yes, no = no, polarity = "true equals count #2",
				}
			elseif yes + no == scan.total and no == scan.second and yes == remainder then
				scan.candidates[#scan.candidates + 1] = {
					slot = slot, yes = yes, no = no, polarity = "false equals count #2",
				}
			end
		end
	end
end

local function callLastOnline(index)
	local fn = global("GetGuildRosterLastOnline")
	if type(fn) ~= "function" then return false, "not a function" end
	local storage = { n = 0 }
	local ok, err = pcall(function()
		local function save(...)
			storage.n = select("#", ...)
			local i
			for i = 1, storage.n do storage[i] = select(i, ...) end
		end
		save(fn(index))
	end)
	if not ok then return false, err end
	return true, storage
end

local function describeReturns(storage)
	local parts = {}
	local allNil = storage.n > 0
	local i
	for i = 1, storage.n do
		local value = storage[i]
		local kind = type(value)
		if value ~= nil then allNil = false end
		if kind == "boolean" then parts[#parts + 1] = "boolean " .. tostring(value)
		elseif kind == "string" then parts[#parts + 1] = "string length " .. tostring(#value)
		elseif kind == "number" then parts[#parts + 1] = "number"
		else parts[#parts + 1] = kind end
	end
	local text = storage.n == 0 and "no values" or table.concat(parts, ", ")
	return text, allNil and storage.n > 0
end

local function collect()
	local scan = {
		found = hints(),
		examined = 0,
		populated = 0,
		empty = 0,
		errors = 0,
		widest = 0,
		slots = {},
		falseIndex = {},
		identityMatches = 0,
		status = "not run",
		reasons = {},
	}
	local infoFn = global("GetGuildInfo")
	local infoOk, info = invoke(infoFn, "player")
	scan.guildCalled = type(infoFn) == "function"
	scan.guildOk = infoOk
	if infoOk then
		rememberGuild(scan.found, info)
		scan.guildInfo = info
	else
		scan.guildError = info
	end

	local inFn = global("IsInGuild")
	scan.inCalled = type(inFn) == "function"
	if scan.inCalled then
		local inOk, inResult = invoke(inFn, "none")
		scan.inOk = inOk
		if inOk then scan.inResult = inResult else scan.inError = inResult end
	end

	noteCounts(scan)
	if scan.countError or type(scan.counts) ~= "table" then
		scan.status = "not run"
		scan.notRun = scan.countError and "GetNumGuildMembers failed" or "GetNumGuildMembers was not called"
		return scan
	end
	if not wholeNumber(scan.total) then
		scan.status = "not run"
		scan.notRun = "GetNumGuildMembers did not return a usable count"
		return scan
	end
	local rosterFn = global("GetGuildRosterInfo")
	if type(rosterFn) ~= "function" then
		scan.status = "not run"
		scan.notRun = "GetGuildRosterInfo was not called"
		return scan
	end

	local limit = scan.total
	if limit > SCAN_CAP then
		limit = SCAN_CAP
		scan.capped = true
	end
	local i
	for i = 1, limit do
		if i > 1 and (i - 1) % 100 == 0 then noteCounts(scan) end
		local rowOk, row = queryIndex(i)
		scan.examined = scan.examined + 1
		if not rowOk then
			scan.errors = scan.errors + 1
			if not scan.firstError then scan.firstError = row end
		elseif hasValue(row) then
			scan.populated = scan.populated + 1
			if row.n > scan.widest then scan.widest = row.n end
			local slot
			for slot = 1, row.n do
				local stats = scan.slots[slot]
				if not stats then
					stats = newSlot()
					scan.slots[slot] = stats
				end
				local value = row[slot]
				recordValue(stats, value)
				if value == false and not scan.falseIndex[slot] then
					scan.falseIndex[slot] = i
				end
			end
			local score = playerScore(row, scan.found)
			if score > (scan.playerScore or 0) then
				scan.playerScore = score
				scan.playerIndex = i
				scan.playerRow = copyRow(row)
				scan.identityMatches = 1
			elseif score > 0 and score == scan.playerScore then
				scan.identityMatches = scan.identityMatches + 1
			end
		else
			scan.empty = scan.empty + 1
		end
	end
	noteCounts(scan)
	finishStatus(scan)
	if scan.playerRow then classifyIdentity(scan) end
	onlineCandidates(scan)
	return scan
end

local function countText(storage)
	if not storage then return "none" end
	local parts = {}
	local i
	for i = 1, storage.n do
		local value = storage[i]
		if type(value) == "string" then
			parts[#parts + 1] = "#" .. tostring(i) .. "=string length " .. tostring(#value)
		else
			parts[#parts + 1] = "#" .. tostring(i) .. "=" .. tostring(value)
		end
	end
	if not parts[1] then return "no values" end
	return table.concat(parts, " ")
end

local function reasonText(scan)
	if scan.status == "not run" then
		return "Scan: not run. " .. (scan.notRun or "The roster was not read.")
	end
	local text = "Scan: " .. scan.status .. ". Examined " .. tostring(scan.examined)
		.. ", populated " .. tostring(scan.populated)
		.. ", empty " .. tostring(scan.empty)
		.. ", errors " .. tostring(scan.errors)
		.. ". Cap " .. tostring(SCAN_CAP) .. "."
	if scan.reasons[1] then
		text = text .. " Reason: " .. table.concat(scan.reasons, ", ") .. "."
		if scan.capped and scan.total then
			text = text .. " Reported count was " .. tostring(scan.total) .. "."
		end
	end
	return text
end

local function eventDelta()
	local delta = eventCount - eventMark
	eventMark = eventCount
	return delta
end

local function addEvents(lines)
	local delta = eventDelta()
	if eventRegistered then
		add(lines, "GUILD_ROSTER_UPDATE registration succeeded. Received " .. tostring(eventCount) .. " time(s) since login, " .. tostring(delta) .. " since the previous probe command.")
	else
		add(lines, "GUILD_ROSTER_UPDATE could not be registered. Received " .. tostring(eventCount) .. " time(s) since login.")
	end
	add(lines, "Last arguments: " .. eventArgs)
end

local function addLastOnline(lines, scan)
	local fn = global("GetGuildRosterLastOnline")
	if type(fn) ~= "function" then
		add(lines, "GetGuildRosterLastOnline was not called.")
		return
	end
	if scan.playerIndex then
		local ok, result = callLastOnline(scan.playerIndex)
		if not ok then
			add(lines, "GetGuildRosterLastOnline(your index) " .. failure(result, scan.found))
		else
			local text, allNil = describeReturns(result)
			add(lines, "GetGuildRosterLastOnline(your index " .. tostring(scan.playerIndex) .. "): " .. text .. ".")
			if allNil then
				add(lines, "Those nil values are a reading. Nil does not mean the function is broken.")
			end
		end
	else
		add(lines, "GetGuildRosterLastOnline was not sampled for you because your row was not identified.")
	end
	local other, label
	if scan.candidates[1] then
		local slot = scan.candidates[1].slot
		other = scan.falseIndex[slot]
		label = "index " .. tostring(other) .. " where field #" .. tostring(slot) .. " is false"
	elseif scan.status == "complete" then
		local slot
		for slot = 1, scan.widest do
			local stats = scan.slots[slot]
			if not other and stats and stats.boolFalse > 0 and scan.falseIndex[slot] then
				other = scan.falseIndex[slot]
				label = "index " .. tostring(other) .. " where field #" .. tostring(slot) .. " is false. That field is not an online candidate"
			end
		end
	end
	if scan.status ~= "complete" then
		add(lines, "Offline-candidate last-online was not sampled because the scan is partial.")
		return
	end
	if not other then
		add(lines, "No false boolean on a candidate field, so an offline-candidate row was not sampled.")
		return
	end
	if other == scan.playerIndex then
		add(lines, "The false candidate row is your own index.")
		return
	end
	local ok, result = callLastOnline(other)
	if not ok then
		add(lines, "GetGuildRosterLastOnline(" .. label .. ") " .. failure(result, scan.found))
	else
		local text, allNil = describeReturns(result)
		add(lines, "GetGuildRosterLastOnline(" .. label .. "): " .. text .. ".")
		if allNil then
			add(lines, "Nil last-online values on that row are a reading, not proof the function is broken.")
		end
	end
end

local function addOnline(lines, scan)
	if scan.status ~= "complete" then
		add(lines, "Boolean comparison needs a complete scan. Online-status mapping remains unverified.")
		return
	end
	if type(scan.second) ~= "number" then
		add(lines, "Count #2 was not a number, so no online candidate was chosen. Online-status mapping remains unverified.")
		return
	end
	if not scan.candidates[1] then
		add(lines, "Online candidate: none. No boolean split equals count #1 and count #2. Online-status mapping remains unverified.")
	else
		local i
		for i = 1, #scan.candidates do
			local item = scan.candidates[i]
			add(lines, "Online candidate: field #" .. tostring(item.slot) .. " true " .. tostring(item.yes) .. ", false " .. tostring(item.no) .. "; " .. item.polarity .. ". Candidate only.")
		end
		add(lines, "Online-status mapping remains unverified.")
	end
	if type(scan.total) == "number" and type(scan.second) == "number" then
		if scan.populated == scan.total and scan.second < scan.total then
			add(lines, "Populated rows equal count #1, and count #2 is smaller. The extra rows were returned. Whether they are offline members is unverified.")
		elseif scan.populated == scan.second and scan.second < scan.total then
			add(lines, "Populated rows equal count #2 and are fewer than count #1. The difference was not returned. Whether those missing rows are offline members is unverified.")
		elseif scan.populated == scan.total and scan.second == scan.total then
			add(lines, "Populated rows equal both counts. The counts do not show a separate offline group.")
		else
			add(lines, "Populated rows do not equal either count. Offline presence is unverified.")
		end
	end
end

local function typeList(slot)
	local parts = {}
	local i
	for i = 1, #TYPE_ORDER do
		local kind = TYPE_ORDER[i]
		local count = slot.types[kind]
		if count and count > 0 then
			parts[#parts + 1] = kind .. " " .. tostring(count)
		end
	end
	return table.concat(parts, ", ")
end

local function fieldLine(index, slot)
	local nonNil = slot.present - slot.nils
	local text = "#" .. tostring(index) .. " seen " .. tostring(slot.present)
		.. ", nil " .. tostring(slot.nils)
		.. ", non-nil " .. tostring(nonNil)
	local types = typeList(slot)
	if types ~= "" then text = text .. "; " .. types end
	if slot.boolTrue + slot.boolFalse > 0 then
		text = text .. "; true " .. tostring(slot.boolTrue) .. ", false " .. tostring(slot.boolFalse)
	end
	if slot.numMin ~= nil then
		text = text .. "; number range " .. tostring(slot.numMin) .. " to " .. tostring(slot.numMax)
	end
	if slot.lenMin ~= nil then
		text = text .. "; string length " .. tostring(slot.lenMin) .. " to " .. tostring(slot.lenMax)
	end
	if slot.emptyStr > 0 then
		text = text .. "; empty strings " .. tostring(slot.emptyStr)
	end
	if slot.playerTags[1] then
		text = text .. "; player " .. table.concat(slot.playerTags, ", ")
	end
	return text
end

local function addIdentity(lines, scan, short)
	if not scan.playerIndex then
		add(lines, "Your character was not identified in the scanned rows.")
		return
	end
	add(lines, "Your row was index " .. tostring(scan.playerIndex) .. ". Rows matching your identity: " .. tostring(scan.identityMatches) .. ".")
	if scan.identityNote then add(lines, scan.identityNote) end
	if not scan.nameField then
		add(lines, "Name field was not identified. Missing and duplicate names were not counted.")
	else
		local scope = scan.status == "complete" and "scanned rows" or "partial scan only"
		add(lines, "Name field #" .. tostring(scan.nameField) .. " (" .. scope .. "): non-empty " .. tostring(scan.nameNon or 0) .. ", missing " .. tostring(scan.nameMissing or 0) .. ", other types " .. tostring(scan.nameOther or 0) .. ", duplicate values " .. tostring(scan.nameDup or 0) .. ", extra copies " .. tostring(scan.nameExtra or 0) .. ".")
	end
	if not scan.guidField then
		add(lines, "No return matched UnitGUID. GUID position was not identified.")
	else
		local scope = scan.status == "complete" and "scanned rows" or "partial scan only"
		add(lines, "GUID field #" .. tostring(scan.guidField) .. " (" .. scope .. "): non-empty " .. tostring(scan.guidNon or 0) .. ", missing " .. tostring(scan.guidMissing or 0) .. ", other types " .. tostring(scan.guidOther or 0) .. ", duplicate values " .. tostring(scan.guidDup or 0) .. ", extra copies " .. tostring(scan.guidExtra or 0) .. ". Format was not checked.")
	end
	if scan.identityErrors and scan.identityErrors > 0 then
		add(lines, "Identity recount errors: " .. tostring(scan.identityErrors) .. ".")
	end
	if not short then
		add(lines, "Names and character ids from the roster were counted in memory and not printed.")
	end
end

local function reportOverview(scan)
	local lines = {}
	local found = scan.found
	add(lines, "Development-only read-only check. GuildRoster() was not called. Nothing is saved.")
	local shown = {
		"IsInGuild", "GetGuildInfo", "GetNumGuildMembers",
		"GetGuildRosterInfo", "GetGuildRosterLastOnline", "GuildRoster",
	}
	local index
	for index = 1, #shown do
		local name = shown[index]
		local value = global(name)
		local suffix = ""
		if type(value) == "function" and NEVER_CALL[name] then suffix = " (present, not called)" end
		add(lines, name .. " = " .. type(value) .. suffix)
	end
	if scan.inCalled and scan.inOk then
		local value = scan.inResult[1]
		local kind = type(value)
		if kind == "boolean" then
			add(lines, "IsInGuild returns boolean " .. tostring(value) .. ".")
		else
			add(lines, "IsInGuild returns " .. kind .. ".")
		end
	elseif scan.inCalled then
		add(lines, "IsInGuild " .. failure(scan.inError, found))
	else
		add(lines, "IsInGuild was not called.")
	end
	if scan.guildCalled and scan.guildOk then
		add(lines, "GetGuildInfo(\"player\") returns " .. tostring(scan.guildInfo.n) .. " value(s).")
		local i
		for i = 1, scan.guildInfo.n do
			local value = scan.guildInfo[i]
			local hidden = type(value) == "string" and (
				value == found.name or value == found.fullJoined or value == found.fullFirst or value == found.guid
			)
			if hidden then
				add(lines, "guild info #" .. tostring(i) .. " string length " .. tostring(#value) .. "; matches your identity and was not printed")
			elseif type(value) == "string" and #value > 0 and #value <= 40 then
				add(lines, "guild info #" .. tostring(i) .. " text=[" .. value .. "]")
			else
				add(lines, "guild info #" .. tostring(i) .. " " .. type(value))
			end
		end
	elseif scan.guildCalled then
		add(lines, "GetGuildInfo " .. failure(scan.guildError, found))
	else
		add(lines, "GetGuildInfo was not called.")
	end
	if type(global("GetGuildRosterInfo")) ~= "function" then
		add(lines, "GetGuildRosterInfo was not called.")
	end
	if scan.counts then
		add(lines, "GetNumGuildMembers " .. countText(scan.counts) .. ".")
		add(lines, "Count #2 is compared with boolean totals only as a candidate. One Forever test saw #1 as total and #2 as online; this probe does not treat that as a contract.")
	end
	if scan.countChanged then
		if scan.countRereadFailed then
			add(lines, "Member count could not be read again during the scan.")
		else
			add(lines, "Member count changed during the scan. Later reading " .. countText(scan.laterCounts) .. ".")
		end
	end
	add(lines, reasonText(scan))
	if scan.errors > 0 then
		add(lines, "API errors: " .. tostring(scan.errors) .. ". First error: " .. failure(scan.firstError, found))
	end
	if scan.status ~= "not run" then
		add(lines, "Widest populated row returned " .. tostring(scan.widest) .. " values.")
		addIdentity(lines, scan, true)
		addOnline(lines, scan)
		addLastOnline(lines, scan)
	end
	addEvents(lines)
	add(lines, "More detail: /ikprobe fields, /ikprobe identity, /ikprobe events.")
	return lines
end

local function reportFields(scan)
	local lines = {}
	add(lines, reasonText(scan))
	if scan.counts then
		add(lines, "GetNumGuildMembers " .. countText(scan.counts) .. ".")
	end
	if scan.status == "not run" then
		add(lines, "Field summary was not collected.")
		add(lines, "Online-status mapping remains unverified.")
		return lines
	end
	add(lines, "Widest populated row returned " .. tostring(scan.widest) .. " values. Stats use populated rows only.")
	local shown = 0
	local slot
	for slot = 1, scan.widest do
		local stats = scan.slots[slot]
		if stats and shown < FIELD_LINE_CAP then
			add(lines, fieldLine(slot, stats))
			shown = shown + 1
		end
	end
	if scan.widest > shown then
		add(lines, "Additional fields were omitted after " .. tostring(shown) .. ".")
	end
	addOnline(lines, scan)
	return lines
end

local function reportIdentity(scan)
	local lines = {}
	add(lines, reasonText(scan))
	if scan.status == "not run" then
		add(lines, "Identity summary was not collected.")
		return lines
	end
	addIdentity(lines, scan, false)
	if scan.status ~= "complete" then
		add(lines, "These identity counts are not a complete guild census.")
	end
	return lines
end

local function reportEvents()
	local lines = {}
	add(lines, "Event check only. The roster was not scanned and GuildRoster() was not called.")
	addEvents(lines)
	add(lines, "Open the guild window, then run /ikprobe events again to compare the counts.")
	return lines
end

local function parseMode(message)
	local text = message or ""
	if type(text) ~= "string" then text = "" end
	text = string.gsub(text, "^%s+", "")
	text = string.gsub(text, "%s+$", "")
	text = string.lower(text)
	if text == "" or text == "overview" then return "overview" end
	if text == "fields" or text == "identity" or text == "events" then return text end
	return "unknown"
end

function IronkeepRosterProbe.Run(mode)
	mode = parseMode(mode)
	if mode == "unknown" then
		local lines = {}
		add(lines, "Unknown command. Use /ikprobe, /ikprobe fields, /ikprobe identity, or /ikprobe events.")
		return lines
	end
	if mode == "events" then return reportEvents() end
	local scan = collect()
	if mode == "fields" then return reportFields(scan) end
	if mode == "identity" then return reportIdentity(scan) end
	return reportOverview(scan)
end

local function describeEvent(value)
	local kind = type(value)
	if kind == "boolean" then return "boolean " .. tostring(value) end
	if kind == "nil" then return "nil" end
	return kind
end

local function onEvent(_, event, ...)
	if event == "GUILD_ROSTER_UPDATE" then
		eventCount = eventCount + 1
		local n = select("#", ...)
		if n == 0 then
			eventArgs = "no arguments"
			return
		end
		local parts = {}
		local i
		for i = 1, n do
			parts[#parts + 1] = describeEvent(select(i, ...))
		end
		eventArgs = table.concat(parts, ", ")
		return
	end
	if event == "PLAYER_ENTERING_WORLD" and not entered then
		entered = true
		IronkeepRosterProbe.Run("overview")
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
SlashCmdList.IKPROBE = function(message)
	return IronkeepRosterProbe.Run(message)
end

if type(print) == "function" then
	print("|cff2dd4bfIronkeep probe|r 0.0.2 loaded. Type /ikprobe, /ikprobe fields, /ikprobe identity, or /ikprobe events.")
end
