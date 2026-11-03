-- Loads the addon the way the client does, with a stand-in for the WoW UI.
-- This runs without a login. It does not prove how Forever draws the window.

local function fail(message)
	error(message or "check failed", 2)
end

local frames = {}

local function widget(kind)
	local w = {
		_kind = kind,
		_shown = true,
		_text = "",
		_w = 0,
		_h = 0,
		_scripts = {},
	}
	function w:SetText(value) self._text = tostring(value or "") end
	function w:GetStringWidth() return #self._text * 7 end
	function w:SetWidth(value) self._w = value end
	function w:SetHeight(value) self._h = value end
	function w:GetWidth() return self._w end
	function w:SetSize(width, height) self._w = width self._h = height end
	function w:Hide() self._shown = false end
	function w:Show() self._shown = true end
	function w:SetShown(on) self._shown = on and true or false end
	function w:IsShown() return self._shown end
	function w:SetFont() return true end
	function w:SetScript(name, fn) self._scripts[name] = fn end
	function w:GetPoint() return "CENTER", nil, "CENTER", 0, 40 end
	function w:GetVerticalScroll() return 0 end
	function w:GetVerticalScrollRange() return 0 end
	function w:GetFrameLevel() return 1 end
	function w:CreateFontString() return widget("FontString") end
	function w:CreateTexture() return widget("Texture") end
	function w:SetBackdrop() end
	return setmetatable(w, {
		__index = function(_, key)
			if type(key) == "string" and key:match("^[A-Z]") then
				return function() end
			end
		end,
	})
end

function CreateFrame(_, name)
	local frame = widget("Frame")
	frame._name = name
	frames[#frames + 1] = frame
	return frame
end

UIParent = widget("Frame")
GameFontHighlightSmall = {}
SlashCmdList = {}
time = os.time
date = os.date
local printed = {}
function print(message) printed[#printed + 1] = tostring(message) end

local raid = {
	raid1 = { "Ada", "Smith", "Warrior", "WARRIOR", "TANK", "guid-a", 1 },
	raid2 = { "Bram", "Holt", "Paladin", "PALADIN", "HEALER", "guid-b", 1 },
	raid3 = { "Dain", "Frost", "Mage", "MAGE", "DAMAGER", "guid-c", 2 },
}

function IsInRaid() return true end
function IsInGroup() return true end
function GetNumGroupMembers()
	local n = 0
	for _ in pairs(raid) do n = n + 1 end
	return n
end
function UnitExists(unit) return raid[unit] ~= nil end
function UnitFullName(unit)
	local person = raid[unit]
	return person[1], person[2]
end
function UnitName(unit) return raid[unit][1] end
function UnitGUID(unit) return raid[unit][6] end
function UnitClass(unit) return raid[unit][3], raid[unit][4] end
function UnitGroupRolesAssigned(unit) return raid[unit][5] end
function GetRaidRosterInfo(index) return nil, nil, raid["raid" .. index][7] end
function GetInstanceInfo() return "Hall of Thanes", "raid" end

dofile("addon/Ironkeep/Group.lua")
dofile("addon/Ironkeep/Window.lua")
dofile("addon/Ironkeep/Core.lua")

local eventFrame
for i = 1, #frames do
	if frames[i]._scripts.OnEvent then eventFrame = frames[i] end
end
if not eventFrame then fail("the addon did not listen for load") end

eventFrame._scripts.OnEvent(eventFrame, "ADDON_LOADED", "Ironkeep")
if not Ironkeep.db then fail("saved data was not created") end
if Ironkeep.Window.IsShown() then fail("the window should stay closed until /ironkeep") end
if not printed[1] or not printed[1]:find("/ironkeep", 1, true) then
	fail("joining a group did not mention /ironkeep")
end

SlashCmdList.IRONKEEP()
if not Ironkeep.Window.IsShown() then fail("/ironkeep did not open the window") end
if Ironkeep.db.open ~= true then fail("the window did not remember that it is open") end

if not Ironkeep.db.session or Ironkeep.db.session.place ~= "Hall of Thanes" then
	fail("the raid place was not kept")
end
local lanes = Ironkeep.Group.Lanes(Ironkeep.db.session)
if lanes[1].label ~= "Tank" or lanes[1].count ~= 1 then fail("Tank lane missing") end
if lanes[2].person.name ~= "Ada Smith" then fail("surname was not kept") end
if lanes[3].label ~= "Healer" then fail("Healer lane missing") end
if lanes[5].label ~= "DPS" or lanes[6].person.name ~= "Dain Frost" then fail("DPS lane missing") end

raid.raid3 = nil
eventFrame._scripts.OnEvent(eventFrame, "GROUP_ROSTER_UPDATE")
lanes = Ironkeep.Group.Lanes(Ironkeep.db.session)
local leftLane
for i = 1, #lanes do
	if lanes[i].kind == "lane" and lanes[i].key == "LEFT" then leftLane = lanes[i + 1] end
end
if not leftLane or leftLane.person.name ~= "Dain Frost" then fail("a leaver did not move under Left") end

-- Copy list is the accent button. Clicking it opens the text.
local opened = false
for i = 1, #frames do
	local click = frames[i]._scripts.OnClick
	local labelWidget = rawget(frames[i], "label")
	local label = labelWidget and labelWidget._text
	if click and label == "Copy list" then
		click(frames[i])
		opened = true
	end
end
if not opened then fail("Copy list button was not created") end
local report
for i = 1, #frames do
	if frames[i]._text and frames[i]._text:find("Ada Smith", 1, true) and frames[i]._text:find("format: ironkeep-group 1", 1, true) then
		report = frames[i]._text
	end
end
if not report then fail("Copy list did not produce the report") end
if not report:find("Dain Frost", 1, true) then fail("the report dropped someone who left") end

io.write("ok\n")
