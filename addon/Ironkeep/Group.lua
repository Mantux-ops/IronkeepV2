-- Read the current party or raid and fold it into one session.
-- WoW: Forever returns a surname from UnitFullName; other clients put a realm there.
-- This addon targets Forever only, so the second name is part of the character.

Ironkeep = Ironkeep or {}
Ironkeep.Group = {}

local ROLE_ORDER = { TANK = 1, HEALER = 2, DAMAGER = 3 }
local ROLE_LABEL = { TANK = "Tank", HEALER = "Healer", DAMAGER = "Damage" }

local function secret(value)
	return type(issecretvalue) == "function" and issecretvalue(value)
end

local function plain(value)
	if secret(value) or type(value) ~= "string" or value == "" or value == "Unknown" then
		return nil
	end
	return value
end

local function num(value)
	if secret(value) or type(value) ~= "number" then return nil end
	return value
end

local function flag(value)
	if secret(value) then return false end
	return value and true or false
end

local function characterName(unit)
	if UnitFullName then
		local first, second = UnitFullName(unit)
		first, second = plain(first), plain(second)
		if first and second then return first .. " " .. second end
		if first then return first end
	end
	if UnitName then return plain(UnitName(unit)) end
	return nil
end

local function unitThere(unit)
	if not UnitExists then return true end
	return flag(UnitExists(unit))
end

local function inRaid()
	if IsInRaid then
		local ok, value = pcall(IsInRaid)
		if not ok or secret(value) then
			return UnitExists and flag(UnitExists("raid1"))
		end
		return value and true or false
	end
	return UnitExists and flag(UnitExists("raid1"))
end

local function eachUnit()
	local units = {}
	if inRaid() then
		local count = GetNumGroupMembers and (num(GetNumGroupMembers()) or 0) or 0
		for i = 1, count do
			local unit = "raid" .. i
			if unitThere(unit) then units[#units + 1] = unit end
		end
		return units
	end
	local inGroup = IsInGroup and flag(IsInGroup())
	local count = GetNumGroupMembers and (num(GetNumGroupMembers()) or 0) or 0
	if not inGroup and count > 0 then inGroup = true end
	if not inGroup then return units end
	if unitThere("player") then units[1] = "player" end
	local others = GetNumSubgroupMembers and (num(GetNumSubgroupMembers()) or 0) or math.max(0, count - 1)
	for i = 1, others do
		local unit = "party" .. i
		if unitThere(unit) then units[#units + 1] = unit end
	end
	return units
end

local function roleOf(unit)
	if not UnitGroupRolesAssigned then return nil end
	local ok, role = pcall(UnitGroupRolesAssigned, unit)
	if not ok then return nil end
	role = plain(role)
	if role == "NONE" then return nil end
	return role
end

local function subgroupOf(unit)
	if not GetRaidRosterInfo then return nil end
	local index = tonumber(unit:match("^raid(%d+)$") or "")
	if not index then return nil end
	local ok, _, _, subgroup = pcall(GetRaidRosterInfo, index)
	if not ok then return nil end
	return num(subgroup)
end

function Ironkeep.Group.Read()
	local snapshot = {
		count = 0,
		place = nil,
		instanceType = nil,
		people = {},
	}
	if GetInstanceInfo then
		local read, place, instanceType = pcall(GetInstanceInfo)
		if read then
			snapshot.place = plain(place)
			snapshot.instanceType = plain(instanceType)
		end
	end
	if not snapshot.place and GetZoneText then
		snapshot.place = plain(GetZoneText())
	end

	local units = eachUnit()
	for i = 1, #units do
		local unit = units[i]
		local named, name = pcall(characterName, unit)
		local identified, guid = pcall(function()
			return UnitGUID and plain(UnitGUID(unit)) or nil
		end)
		name = named and name or nil
		guid = identified and guid or nil
		if name or guid then
			local classFile, className
			if UnitClass then
				local read, localized, file = pcall(UnitClass, unit)
				if read then
					classFile = plain(file)
					className = plain(localized)
				end
			end
			snapshot.people[#snapshot.people + 1] = {
				guid = guid,
				name = name,
				classFile = classFile,
				className = className,
				role = roleOf(unit),
				subgroup = subgroupOf(unit),
			}
		end
	end
	snapshot.count = #snapshot.people
	return snapshot
end

function Ironkeep.Group.NewSession(snapshot, now)
	return {
		place = snapshot.place or "Unknown",
		instanceType = snapshot.instanceType,
		started = now,
		touched = now,
		people = {},
	}
end

function Ironkeep.Group.ShouldRestart(session, snapshot, now, idleSeconds)
	if not session then return snapshot.count > 0 end
	if snapshot.count == 0 then return false end
	for _, person in pairs(session.people) do
		if person.present then return false end
	end
	return now - (session.touched or now) >= idleSeconds
end

function Ironkeep.Group.Merge(session, snapshot, now)
	local seen = {}
	for i = 1, #snapshot.people do
		local incoming = snapshot.people[i]
		local key = incoming.guid or incoming.name
		if key then
			seen[key] = true
			local row = session.people[key]
			if not row then
				row = { first = now }
				session.people[key] = row
			end
			row.last = now
			row.present = true
			if incoming.name and (not row.name or #incoming.name > #row.name) then
				row.name = incoming.name
			end
			row.classFile = incoming.classFile or row.classFile
			row.className = incoming.className or row.className
			if incoming.role then row.role = incoming.role end
			if incoming.subgroup then row.subgroup = incoming.subgroup end
		end
	end
	for key, row in pairs(session.people) do
		if not seen[key] and row.present then
			row.present = false
			row.last = now
		end
	end
	if snapshot.count > 0 then session.touched = now end
	if snapshot.instanceType == "party" or snapshot.instanceType == "raid" then
		if snapshot.place then session.place = snapshot.place end
		session.instanceType = snapshot.instanceType
	elseif snapshot.place and session.place == "Unknown" then
		session.place = snapshot.place
	end
end

function Ironkeep.Group.Seen(person)
	if not person.first or not person.last then return "" end
	local minutes = math.floor((person.last - person.first) / 60)
	if minutes < 1 then return "<1m" end
	if minutes < 60 then return minutes .. "m" end
	return math.floor(minutes / 60) .. "h " .. (minutes % 60) .. "m"
end

function Ironkeep.Group.Rows(session)
	local rows = {}
	if not session then return rows end
	for _, person in pairs(session.people) do
		rows[#rows + 1] = person
	end
	table.sort(rows, function(a, b)
		if a.present ~= b.present then return a.present and not b.present end
		local aGroup, bGroup = a.subgroup or 99, b.subgroup or 99
		if aGroup ~= bGroup then return aGroup < bGroup end
		local aRole = ROLE_ORDER[a.role] or 9
		local bRole = ROLE_ORDER[b.role] or 9
		if aRole ~= bRole then return aRole < bRole end
		return (a.name or "") < (b.name or "")
	end)
	return rows
end

function Ironkeep.Group.RoleLabel(role)
	return ROLE_LABEL[role] or ""
end

local LANES = {
	{ key = "TANK", label = "Tank" },
	{ key = "HEALER", label = "Healer" },
	{ key = "DAMAGER", label = "DPS" },
	{ key = "NONE", label = "Group" },
	{ key = "LEFT", label = "Left" },
}

-- The site lists a raid by role, not as one table. People who left sit in their own lane.
function Ironkeep.Group.Lanes(session)
	local items = {}
	if not session then return items end
	local buckets = { TANK = {}, HEALER = {}, DAMAGER = {}, NONE = {}, LEFT = {} }
	local people = Ironkeep.Group.Rows(session)
	for i = 1, #people do
		local person = people[i]
		if person.present then
			local key = buckets[person.role] and person.role or "NONE"
			buckets[key][#buckets[key] + 1] = person
		else
			buckets.LEFT[#buckets.LEFT + 1] = person
		end
	end
	for i = 1, #LANES do
		local lane = LANES[i]
		local list = buckets[lane.key]
		if #list > 0 then
			items[#items + 1] = { kind = "lane", key = lane.key, label = lane.label, count = #list }
			for n = 1, #list do
				items[#items + 1] = { kind = "person", person = list[n] }
			end
		end
	end
	return items
end

function Ironkeep.Group.Report(session, now)
	if not session then
		return "Ironkeep group\n\nNobody recorded yet."
	end
	local when = date("%Y-%m-%d %H:%M", session.started or now)
	local lines = {
		"Ironkeep group",
		"Place: " .. (session.place or "Unknown"),
		"Started: " .. when,
		"",
		"Name | Class | Role | Time | Status",
	}
	local rows = Ironkeep.Group.Rows(session)
	for i = 1, #rows do
		local person = rows[i]
		local status = person.present and "here" or "left"
		lines[#lines + 1] = table.concat({
			person.name or "Unknown",
			person.className or person.classFile or "",
			Ironkeep.Group.RoleLabel(person.role),
			Ironkeep.Group.Seen(person),
			status,
		}, " | ")
	end
	if #rows == 0 then
		lines[#lines + 1] = "Nobody recorded yet."
	end
	lines[#lines + 1] = ""
	lines[#lines + 1] = "format: ironkeep-group 1"
	return table.concat(lines, "\n")
end
