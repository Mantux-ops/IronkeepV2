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
	function w:SetText(value)
		local text = tostring(value or "")
		-- A positive letter cap truncates, matching the Forever edit box. Zero does not.
		if self._maxLetters and self._maxLetters > 0 and #text > self._maxLetters then
			text = text:sub(1, self._maxLetters)
		end
		self._text = text
	end
	function w:SetMaxLetters(value) self._maxLetters = value end
	function w:HasFocus() return self._focus and true or false end
	function w:SetFocus()
		self._focusCount = (self._focusCount or 0) + 1
		if self._focusCount > 12 then error("focus loop") end
		if self._focus and self._scripts.OnEditFocusLost then
			self._scripts.OnEditFocusLost(self)
		end
		self._focus = true
		if self._scripts.OnEditFocusGained then
			self._scripts.OnEditFocusGained(self)
		end
	end
	function w:ClearFocus()
		self._clearCount = (self._clearCount or 0) + 1
		if self._clearCount > 12 then error("focus loop") end
		if not self._focus then return end
		-- Fire while focus is still held, which is the loop the window must survive.
		if self._scripts.OnEditFocusLost then
			self._scripts.OnEditFocusLost(self)
		end
		self._focus = false
	end
	function w:HighlightText()
		self._highlights = (self._highlights or 0) + 1
		self._highlighted = self._text
	end
	function w:SetPoint(...)
		local point = {}
		for i = 1, select("#", ...) do point[i] = select(i, ...) end
		self._points = self._points or {}
		self._points[#self._points + 1] = point
	end
	function w:ClearAllPoints()
		self._points = {}
	end
	function w:SetVerticalScroll(value) self._scroll = value end
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
	function w:RegisterEvent(event)
		self._events = self._events or {}
		self._events[#self._events + 1] = event
	end
	function w:GetPoint() return "CENTER", nil, "CENTER", 0, 40 end
	function w:GetVerticalScroll() return self._scroll or 0 end
	function w:GetVerticalScrollRange() return self._scrollMax or 0 end
	function w:GetFrameLevel() return 1 end
	function w:CreateFontString()
		local font = widget("FontString")
		frames[#frames + 1] = font
		return font
	end
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
dofile("addon/IronkeepRoster/Roster.lua")

local eventFrame
for i = 1, #frames do
	local events = frames[i]._events
	if events then
		for e = 1, #events do
			if events[e] == "ADDON_LOADED" then eventFrame = frames[i] end
		end
	end
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

local function frameNamed(name)
	for i = 1, #frames do
		if frames[i]._name == name then return frames[i] end
	end
end

local function statValue(caption)
	for i = 1, #frames do
		if frames[i]._stat == caption then return frames[i]._value end
	end
end

local function shownRow(name)
	for i = 1, #frames do
		local frame = frames[i]
		if frame._attendance and frame:IsShown() and frame._member == name then return frame end
	end
end

local function hasExactText(text)
	for i = 1, #frames do
		if frames[i]._text == text and frames[i]:IsShown() then return true end
	end
	return false
end

local function sessionKind()
	for i = 1, #frames do
		if frames[i]._sessionKind and frames[i]:IsShown() then return frames[i]._text end
	end
	return ""
end

local function capNote()
	for i = 1, #frames do
		if frames[i]._capNote and frames[i]:IsShown() then return frames[i]._text end
	end
	return ""
end

local main = frameNamed("IronkeepFrame")
if not main or main._w ~= 850 or main._h ~= 550 then fail("the window is not 850 by 550") end
if not hasExactText("Ironkeep") then fail("the header does not show the Ironkeep name") end
local headings = { "Member", "Class", "Role", "Group", "Time", "Status" }
local function columnX(text)
	for i = 1, #frames do
		local points = frames[i]._text == text and frames[i]._points
		if points then
			for p = 1, #points do
				if points[p][1] == "TOPLEFT" and type(points[p][4]) == "number" then return points[p][4] end
			end
		end
	end
end
local previousX = -1
for i = 1, #headings do
	if not hasExactText(headings[i]) then fail("the attendance table is missing " .. headings[i]) end
	local x = columnX(headings[i])
	if not x or x <= previousX then fail("the " .. headings[i] .. " column overlaps the previous one") end
	previousX = x
end
if statValue("Recorded") ~= "3" or statValue("Present") ~= "2" or statValue("Left") ~= "1" then
	fail("the summary counts are not recorded 3, present 2, left 1")
end
local function statFrame(caption)
	for i = 1, #frames do
		if frames[i]._stat == caption then return frames[i] end
	end
end
local recordedCard = statFrame("Recorded")
local presentCard = statFrame("Present")
local leftCard = statFrame("Left")
if not recordedCard or not presentCard or not leftCard then fail("a statistic card is missing") end
if recordedCard._w ~= 168 or recordedCard._h ~= 30 or presentCard._w ~= recordedCard._w or presentCard._h ~= recordedCard._h or leftCard._w ~= recordedCard._w or leftCard._h ~= recordedCard._h then
	fail("the statistic cards are not the same size")
end
if recordedCard._fill ~= presentCard._fill or presentCard._fill ~= leftCard._fill or not recordedCard._flatBorder then
	fail("the statistic cards do not share one panel")
end
if recordedCard._accent == presentCard._accent or presentCard._accent == leftCard._accent or recordedCard._accent == leftCard._accent then
	fail("the statistic cards do not have distinct accents")
end
if not main._flatBorder then fail("the window still uses a tiled edge texture") end
if not hasExactText("Hall of Thanes") then fail("the location is not shown") end
if sessionKind() ~= "Raid" then fail("a raid did not show its group type") end
if capNote() ~= "" then fail("a short list showed the 200-row notice") end
local started = date("%H:%M", Ironkeep.db.session.started)
if not hasExactText(started) then fail("the start time is not shown") end

local ada = shownRow("Ada Smith")
if not ada or ada._class ~= "Warrior" or ada._role ~= "Tank" or ada._status ~= "Here" or ada._time ~= "<1m" then
	fail("Ada is not shown as a present warrior tank")
end
if not ada._color or ada._color[1] ~= 0.91 or ada._color[2] ~= 0.78 or ada._color[3] ~= 0.62 then
	fail("Ada is not shown in the readable warrior color")
end
if ada._group ~= "1" then fail("Ada's raid group is not shown") end
local dain = shownRow("Dain Frost")
if not dain or dain._class ~= "Mage" or dain._role ~= "Damage" or dain._status ~= "Left" or dain._group ~= "2" then
	fail("Dain is not shown as a mage who left group 2")
end
if not dain._color or dain._color[1] ~= 0.41 or dain._color[2] ~= 0.80 or dain._color[3] ~= 0.94 then
	fail("Dain is not colored as a mage")
end
local adaRow = Ironkeep.db.session.people["guid-a"]
local savedFile, savedName = adaRow.classFile, adaRow.className
adaRow.classFile = "HUNTER"
adaRow.className = "Hunter"
Ironkeep.Window.Update()
ada = shownRow("Ada Smith")
if not ada or ada._class ~= "Hunter" or ada._color[1] ~= 0.82 or ada._color[2] ~= 0.94 or ada._color[3] ~= 0.62 then
	fail("a hunter name was not given a readable display color")
end
adaRow.classFile = savedFile
adaRow.className = savedName
Ironkeep.Window.Update()
ada = shownRow("Ada Smith")
if not ada or ada._color[1] ~= 0.91 then fail("the warrior color did not return") end
adaRow.subgroup = nil
Ironkeep.Window.Update()
ada = shownRow("Ada Smith")
if not ada or ada._group ~= "" then fail("a missing subgroup was shown as a group") end
adaRow.subgroup = 1
Ironkeep.Window.Update()

Ironkeep.db.session.instanceType = "none"
Ironkeep.Window.Update()
if sessionKind() ~= "" then fail("an ordinary zone showed a group type") end
Ironkeep.db.session.instanceType = "raid"
Ironkeep.Window.Update()
if sessionKind() ~= "Raid" then fail("the raid type did not return") end

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

-- The stand-in records focus and applies a positive letter cap. It does not press Ctrl+C.
local function clickLabel(text)
	for i = 1, #frames do
		local click = frames[i]._scripts.OnClick
		local labelWidget = rawget(frames[i], "label")
		local label = labelWidget and labelWidget._text
		if click and label == text then
			click(frames[i])
			return true
		end
	end
	return false
end

local function pointOf(frame, anchor)
	local points = frame._points
	if not points then return nil end
	local found
	for i = 1, #points do
		if points[i][1] == anchor then found = points[i] end
	end
	return found
end

local box
for i = 1, #frames do
	local text = frames[i]._text
	if text and frames[i]._maxLetters ~= nil and text:find("format: ironkeep-group 1", 1, true) then
		box = frames[i]
	end
end
if not box then fail("the report box was not found") end
if box._maxLetters ~= 0 then fail("the report box still has a letter cap") end
local expected = Ironkeep.Group.Report(Ironkeep.db.session, time())
if box._text ~= expected then fail("opened report does not match Group.Report") end
if not box:HasFocus() then fail("opening Copy list did not focus the report") end
if box._highlighted ~= expected then fail("opening Copy list did not select the report") end

local reportScroll
for i = 1, #frames do
	if frames[i]._w == 818 and frames[i]._h and frames[i]._h >= 120 and frames[i]._h <= 150 then
		reportScroll = frames[i]
	end
end
if not reportScroll then fail("the report area is not 120 to 150 pixels tall") end
local reportPoint = pointOf(reportScroll, "BOTTOMLEFT")
if not reportPoint or reportPoint[2] ~= 16 or reportPoint[3] ~= 48 then
	fail("the report area moved off the bottom controls")
end
local reportTop = reportPoint[3] + reportScroll._h

local hint
for i = 1, #frames do
	local text = frames[i]._text
	if text and text:find("Ctrl+C", 1, true) and text:find("selected", 1, true) and text:find("this computer", 1, true) then
		hint = frames[i]
	end
end
if not hint then fail("the copy hint does not explain the selection") end
local hintPoint = pointOf(hint, "BOTTOMLEFT")
if not hintPoint or hintPoint[3] < reportTop then fail("the copy hint overlaps the report") end

local listBottom
local listFrame
for i = 1, #frames do
	local point = pointOf(frames[i], "BOTTOMRIGHT")
	if point and point[2] == -12 and type(point[3]) == "number" then
		listBottom = point[3]
		listFrame = frames[i]
	end
end
if not listFrame or not listFrame:IsShown() then fail("the group list is hidden while the report is open") end
if not listBottom or listBottom < hintPoint[3] + 28 then fail("the group list overlaps the copy hint") end
if 550 - 132 - listBottom < 140 then fail("the group list has too little room while the report is open") end

local focuses = box._focusCount
box._scripts.OnEscapePressed(box)
if box:HasFocus() then fail("Escape left the report focused") end
if box._focusCount ~= focuses then fail("leaving the report focused it again") end
if not clickLabel("Hide") then fail("the report did not stay open until Hide") end

Ironkeep.db.lastReport = "Ironkeep group\n\nPrevious marker\n\nformat: ironkeep-group 1"
if not clickLabel("Previous") then fail("Previous was not created") end
if box._text ~= Ironkeep.db.lastReport then fail("Previous did not show the stored report") end
if box._highlighted ~= box._text or not box:HasFocus() then fail("Previous did not select the report") end
if not hint._text:find("Previous", 1, true) then fail("the previous hint was not shown") end
if not clickLabel("Current") then fail("Current was not created") end
expected = Ironkeep.Group.Report(Ironkeep.db.session, time())
if box._text ~= expected then fail("Current did not restore Group.Report") end
if box._highlighted ~= expected then fail("Current did not select the report") end

if not clickLabel("Hide") then fail("Hide did not close the report") end
if box:HasFocus() then fail("closing Copy list left the report focused") end
local stamp = Ironkeep.db.session.started or 0
for n = 1, 50 do
	Ironkeep.db.session.people["long-" .. n] = {
		name = string.rep("N", 160) .. n,
		className = "Warrior",
		classFile = "WARRIOR",
		role = "DAMAGER",
		present = true,
		first = stamp,
		last = stamp,
		subgroup = 1,
	}
end
local people = 0
for _ in pairs(Ironkeep.db.session.people) do people = people + 1 end
if people <= 40 then fail("the long report fixture has too few players") end
if not clickLabel("Copy list") then fail("Copy list did not reopen") end
expected = Ironkeep.Group.Report(Ironkeep.db.session, time())
if #expected <= 8000 then fail("the long report fixture does not pass the old letter cap") end
if box._text ~= expected then
	fail("long report differs from Group.Report (" .. #box._text .. " vs " .. #expected .. ")")
end
if box._text:sub(-24) ~= "format: ironkeep-group 1" then fail("the long report dropped its trailer") end
if box._highlighted ~= expected or not box:HasFocus() then fail("the long report was not selected") end
local _, breaks = expected:gsub("\n", "\n")
if box._h < math.max(reportScroll._h, (breaks + 1) * 14) then
	fail("the long report is clipped to the visible box")
end

reportScroll._scrollMax = 400
reportScroll:SetVerticalScroll(0)
reportScroll._scripts.OnMouseWheel(reportScroll, -1)
if reportScroll:GetVerticalScroll() <= 0 then fail("the report area does not scroll") end
local scrolled = reportScroll:GetVerticalScroll()
box._scripts.OnMouseWheel(box, -1)
if reportScroll:GetVerticalScroll() <= scrolled then
	fail("wheeling over the text did not scroll the report")
end

if not clickLabel("Hide") then fail("Hide failed after the long report") end
Ironkeep.db.session.people["long-1"].name = "Changed Name"
if not clickLabel("Copy list") then fail("Copy list did not reopen after a change") end
expected = Ironkeep.Group.Report(Ironkeep.db.session, time())
if box._text ~= expected then fail("reopening did not refresh the changed report") end
if not box._text:find("Changed Name", 1, true) then fail("the changed name was not copied") end
if box._highlighted ~= expected then fail("the refreshed report was not selected") end

for _ = 1, 3 do
	if not clickLabel("Hide") then fail("repeated Hide failed") end
	if not clickLabel("Copy list") then fail("repeated Copy list failed") end
end
if box._text ~= Ironkeep.Group.Report(Ironkeep.db.session, time()) then
	fail("opening Copy list again changed the report")
end

if not clickLabel("Clear") then fail("Clear was not created") end
local confirmShown = false
for i = 1, #frames do
	if frames[i]._text == "Clear this list?" and frames[i]:IsShown() then confirmShown = true end
end
if not confirmShown then fail("Clear did not ask for confirmation") end
if Ironkeep.db.session.place ~= "Hall of Thanes" then fail("Clear asked by removing the session") end
if not clickLabel("Cancel") then fail("Cancel was not created") end
for i = 1, #frames do
	if frames[i]._text == "Clear this list?" and frames[i]:IsShown() then
		fail("Cancel left the confirmation open")
	end
end
if box._text ~= expected then fail("Cancel changed the report") end

local function expectFocusError(action, needle)
	local ok, err = pcall(action)
	if ok then fail(needle .. " error was swallowed") end
	if not tostring(err):find(needle, 1, true) then
		fail(needle .. " error was hidden: " .. tostring(err))
	end
end

local function assertUpdateStillRuns(marker)
	local place = Ironkeep.db.session.place
	Ironkeep.db.session.place = marker
	Ironkeep.Window.Update()
	local found = false
	for i = 1, #frames do
		if frames[i]._text == marker then found = true end
	end
	Ironkeep.db.session.place = place
	Ironkeep.Window.Update()
	if not found then fail("a focus error left the window unable to update") end
end

if not clickLabel("Hide") then fail("Hide failed before the focus-lock checks") end
local originalHighlight = box.HighlightText
box.HighlightText = function() error("highlight failed") end
expectFocusError(function() clickLabel("Copy list") end, "highlight failed")
box.HighlightText = originalHighlight
assertUpdateStillRuns("AfterHighlight")

if not clickLabel("Hide") then fail("Hide failed before SetFocus check") end
local originalSetFocus = box.SetFocus
box.SetFocus = function() error("setfocus failed") end
expectFocusError(function() clickLabel("Copy list") end, "setfocus failed")
box.SetFocus = originalSetFocus
assertUpdateStillRuns("AfterSetFocus")

if box:HasFocus() then box:ClearFocus() end
if not clickLabel("Hide") then fail("Hide failed before reopening for ClearFocus") end
if not clickLabel("Copy list") then fail("Copy list failed before ClearFocus check") end
local originalClear = box.ClearFocus
box.ClearFocus = function() error("clearfocus failed") end
expectFocusError(function() clickLabel("Hide") end, "clearfocus failed")
box.ClearFocus = originalClear
assertUpdateStillRuns("AfterClearFocus")
if Ironkeep.db.session.place ~= "Hall of Thanes" then fail("the focus-lock checks changed the place") end

local function shownRows()
	local count = 0
	for i = 1, #frames do
		local frame = frames[i]
		if frame._attendance and frame:IsShown() and frame._member then count = count + 1 end
	end
	return count
end

local capName = "Cap Person Extra"
local stamp = Ironkeep.db.session.started or 0
local existing = 0
for _ in pairs(Ironkeep.db.session.people) do existing = existing + 1 end
for n = existing + 1, 210 do
	Ironkeep.db.session.people["cap-" .. n] = {
		name = n == 210 and capName or ("Cap " .. n),
		className = "Mage",
		classFile = "MAGE",
		role = "DAMAGER",
		present = true,
		first = stamp,
		last = stamp,
		subgroup = 1,
	}
end
Ironkeep.Window.Update()
if shownRows() ~= 200 then fail("the attendance table drew more or less than 200 rows") end
local total = 0
for _ in pairs(Ironkeep.db.session.people) do total = total + 1 end
if capNote() ~= "Showing 200 of " .. total .. " members" then
	fail("the row cap did not say how many members are hidden")
end
local cappedReport = Ironkeep.Group.Report(Ironkeep.db.session, time())
if not cappedReport:find(capName, 1, true) or not cappedReport:find("format: ironkeep-group 1", 1, true) then
	fail("the row cap changed the exported report")
end
if cappedReport:find("Showing 200", 1, true) then fail("the row cap notice was written into the report") end

local events = eventFrame._events or {}
local expectedEvents = {
	"ADDON_LOADED",
	"GROUP_ROSTER_UPDATE",
	"PARTY_MEMBERS_CHANGED",
	"RAID_ROSTER_UPDATE",
	"PLAYER_ENTERING_WORLD",
}
if #events ~= #expectedEvents then fail("the event list changed") end
for i = 1, #expectedEvents do
	if events[i] ~= expectedEvents[i] then fail("event " .. tostring(events[i]) .. " is not " .. expectedEvents[i]) end
end

local function readFile(path)
	local handle = io.open(path, "r")
	if not handle then fail("missing " .. path) end
	local text = handle:read("*a")
	handle:close()
	return text
end

local coreText = readFile("addon/Ironkeep/Core.lua")
if not coreText:find("if elapsed < 30", 1, true) then fail("the refresh interval changed") end
if not coreText:find('SLASH_IRONKEEP1 = "/ironkeep"', 1, true) then fail("/ironkeep changed") end
if not coreText:find('SLASH_IRONKEEP2 = "/ik"', 1, true) then fail("/ik changed") end
local bindings = readFile("addon/Ironkeep/Bindings.xml")
if not bindings:find("IRONKEEP_TOGGLE", 1, true) then fail("the key binding changed") end
local rosterToc = readFile("addon/IronkeepRoster/IronkeepRoster.toc")
if rosterToc:find("IronkeepDB", 1, true) or not rosterToc:find("IronkeepRosterDB", 1, true) then
	fail("the roster saved variable changed")
end

if SlashCmdList.IRONKEEP == SlashCmdList.IKROSTER then fail("the roster command replaced the group command") end
if SLASH_IRONKEEP1 ~= "/ironkeep" or SLASH_IKROSTER1 ~= "/ikroster" then
	fail("slash commands were not registered separately")
end
local kept = Ironkeep.db
SlashCmdList.IKROSTER()
if Ironkeep.db ~= kept then fail("a roster scan replaced the group list") end
if kept.session.place ~= "Hall of Thanes" then fail("a roster scan changed the group place") end
if IronkeepRosterDB ~= nil then fail("a roster scan published without guild data") end

io.write("ok\n")
