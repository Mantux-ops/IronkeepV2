-- Reads a fake Forever group without a WoW client.

date = os.date
Ironkeep = {}
dofile("addon/Ironkeep/Group.lua")

local function assertTrue(value, message)
	if not value then error(message or "expected true") end
end

local secretFlag = {}
issecretvalue = function(value) return value == secretFlag end

local function find(snapshot, name)
	for i = 1, #snapshot.people do
		if snapshot.people[i].name == name then return snapshot.people[i] end
	end
	return nil
end

UnitFullName = function(unit)
	if unit == "player" then return "Chehul", "Druida" end
	if unit == "party1" then return "Ada", secretFlag end
	if unit == "party2" then return "Bram", nil end
	if unit == "raid1" then return "Chehul", "Druida" end
	if unit == "raid2" then return "Ada", "Smith" end
	return nil
end
UnitName = function(unit)
	if unit == "player" or unit == "raid1" then return "Chehul" end
	if unit == "party1" or unit == "raid2" then return "Ada" end
	if unit == "party2" then return "Bram" end
end
IsInRaid = function() return false end
IsInGroup = function() return true end
GetNumGroupMembers = function() return 3 end
GetNumSubgroupMembers = function() return 2 end
UnitExists = function(unit)
	return unit == "player" or unit == "party1" or unit == "party2"
end
UnitGUID = function(unit) return "guid-" .. unit end
UnitClass = function(unit)
	if unit == "player" then return "Druid", "DRUID" end
	if unit == "party1" then return "Warrior", "WARRIOR" end
	if unit == "party2" then return secretFlag, secretFlag end
	return nil
end
UnitGroupRolesAssigned = function(unit)
	if unit == "player" then return "HEALER" end
	if unit == "party1" then return "NONE" end
	if unit == "party2" then return "DAMAGER" end
	return "NONE"
end
GetInstanceInfo = function() return "The Stockade", "party" end

local party = Ironkeep.Group.Read()
assertTrue(party.count == 3, "party lists the player and both party units")
assertTrue(party.place == "The Stockade")
assertTrue(party.instanceType == "party")
local chehul = find(party, "Chehul Druida")
assertTrue(chehul and chehul.role == "HEALER" and chehul.classFile == "DRUID", "surname and class come from the unit")
local ada = find(party, "Ada")
assertTrue(ada and ada.role == nil, "a secret surname is dropped and an empty role stays empty")
local bram = find(party, "Bram")
assertTrue(bram and bram.classFile == nil and bram.role == "DAMAGER", "a secret class is skipped")

IsInRaid = function() return secretFlag end
GetNumGroupMembers = function() return 2 end
GetNumSubgroupMembers = function() return 0 end
UnitExists = function(unit) return unit == "raid1" or unit == "raid2" end
GetRaidRosterInfo = function(index) return nil, nil, index end
UnitClass = function() return "Warrior", "WARRIOR" end
UnitGroupRolesAssigned = function() return "TANK" end
GetInstanceInfo = function() return "Hall of Thanes", "raid" end

local raid = Ironkeep.Group.Read()
assertTrue(raid.count == 2, "a secret raid check falls back to raid units")
assertTrue(raid.instanceType == "raid")
assertTrue(find(raid, "Chehul Druida").subgroup == 1)
assertTrue(find(raid, "Ada Smith").subgroup == 2)

print("ok")
