-- Pure checks for the group session. No WoW client.

date = os.date
Ironkeep = {}
dofile("addon/Ironkeep/Group.lua")

local function assertTrue(value, message)
	if not value then error(message or "expected true") end
end

local function person(guid, name, classFile, className, role)
	return {
		guid = guid,
		name = name,
		classFile = classFile,
		className = className,
		role = role,
		subgroup = 1,
	}
end

local now = 1700000000
local first = {
	count = 2,
	place = "Stormwind",
	instanceType = "none",
	people = {
		person("a", "Chehul", "DRUID", "Druid", "HEALER"),
		person("b", "Ada", "WARRIOR", "Warrior", "TANK"),
	},
}

assertTrue(Ironkeep.Group.ShouldRestart(nil, first, now, 1200))
assertTrue(not Ironkeep.Group.ShouldRestart(nil, { count = 0, people = {} }, now, 1200))

local session = Ironkeep.Group.NewSession(first, now)
Ironkeep.Group.Merge(session, first, now)

local named = {
	count = 2,
	place = "Hall of Thanes",
	instanceType = "raid",
	people = {
		person("a", "Chehul Druida", "DRUID", "Druid", "HEALER"),
		person("b", "Ada", "WARRIOR", "Warrior", "TANK"),
	},
}
Ironkeep.Group.Merge(session, named, now + 60)
assertTrue(session.place == "Hall of Thanes", "instance name replaces the city")

local withoutAda = {
	count = 1,
	place = "Hall of Thanes",
	instanceType = "raid",
	people = {
		person("a", "Chehul Druida", "DRUID", "Druid", "HEALER"),
	},
}
Ironkeep.Group.Merge(session, withoutAda, now + 600)
Ironkeep.Group.Merge(session, withoutAda, now + 1200)

local report = Ironkeep.Group.Report(session, now + 1200)
local chehul, ada
for line in report:gmatch("[^\n]+") do
	if line:find("Chehul", 1, true) then chehul = line end
	if line:find("Ada |", 1, true) then ada = line end
end
assertTrue(chehul and chehul:find("Chehul Druida", 1, true), "surname replaces the short name")
assertTrue(chehul:find("20m", 1, true), "someone still inside keeps accumulating time")
assertTrue(chehul:find("here", 1, true))
assertTrue(ada and ada:find("10m", 1, true), "leaving stamps the time once")
assertTrue(ada:find("left", 1, true))
assertTrue(not ada:find("20m", 1, true))
assertTrue(report:find("Chehul", 1, true) < report:find("Ada", 1, true), "people still inside sort first")
assertTrue(report:find("format: ironkeep-group 1", 1, true))

local kept = nil
for _, row in pairs(session.people) do
	if row.name == "Chehul Druida" then kept = row.role end
end
Ironkeep.Group.Merge(session, {
	count = 1,
	place = "Hall of Thanes",
	instanceType = "raid",
	people = { person("a", "Chehul Druida", "DRUID", "Druid", nil) },
}, now + 1260)
for _, row in pairs(session.people) do
	if row.name == "Chehul Druida" then
		assertTrue(row.role == kept and kept == "HEALER", "an empty role does not wipe the last one")
	end
end

assertTrue(not Ironkeep.Group.ShouldRestart(session, withoutAda, now + 1200, 1200))
for _, row in pairs(session.people) do row.present = false end
session.touched = now
assertTrue(Ironkeep.Group.ShouldRestart(session, withoutAda, now + 1300, 1200))

print("ok")
