-- The in-game list. Closed by default. /ironkeep opens it.
-- Drag the title. The report box is there to copy, not to edit.

Ironkeep = Ironkeep or {}
Ironkeep.Window = {}

local GOLD = { 0.776, 0.631, 0.353 }
local INK = { 0.09, 0.08, 0.07, 0.96 }
local EDGE = { 0.45, 0.36, 0.22, 1 }
local ROW_H = 22
local ROW_CAP = 200

local CLASS_COLOR = {
	WARRIOR = { 0.78, 0.61, 0.43 },
	PALADIN = { 0.96, 0.55, 0.73 },
	HUNTER = { 0.67, 0.83, 0.45 },
	ROGUE = { 1.00, 0.96, 0.41 },
	PRIEST = { 1.00, 1.00, 1.00 },
	SHAMAN = { 0.00, 0.44, 0.87 },
	MAGE = { 0.41, 0.80, 0.94 },
	WARLOCK = { 0.58, 0.51, 0.79 },
	DRUID = { 1.00, 0.49, 0.04 },
}

local window
local rows = {}
local reportBox

local function white(parent)
	local texture = parent:CreateTexture(nil, "BACKGROUND")
	texture:SetTexture("Interface\\Buttons\\WHITE8X8")
	return texture
end

local function paint(frame, r, g, b, a)
	if frame.SetBackdrop then
		local ok = pcall(frame.SetBackdrop, frame, {
			bgFile = "Interface\\Buttons\\WHITE8X8",
			edgeFile = "Interface\\Buttons\\WHITE8X8",
			edgeSize = 1,
			insets = { left = 1, right = 1, top = 1, bottom = 1 },
		})
		if ok then
			frame:SetBackdropColor(r, g, b, a or 1)
			frame:SetBackdropBorderColor(EDGE[1], EDGE[2], EDGE[3], EDGE[4])
			return
		end
	end
	local bg = white(frame)
	bg:SetAllPoints()
	bg:SetVertexColor(r, g, b, a or 1)
end

local function frameWithBackdrop(name, parent)
	local ok, created = pcall(CreateFrame, "Frame", name, parent, "BackdropTemplate")
	if ok and created then return created end
	return CreateFrame("Frame", name, parent)
end

local function button(parent, label, width)
	local ok, created = pcall(CreateFrame, "Button", nil, parent, "UIPanelButtonTemplate")
	local widget = (ok and created) or CreateFrame("Button", nil, parent)
	widget:SetSize(width, 22)
	widget:SetText(label)
	if widget.SetNormalFontObject then widget:SetNormalFontObject(GameFontHighlightSmall) end
	return widget
end

local function savePoint()
	if not window or not Ironkeep.db then return end
	local point, _, _, x, y = window:GetPoint(1)
	Ironkeep.db.point = point
	Ironkeep.db.x = x
	Ironkeep.db.y = y
end

local function kindLabel(instanceType)
	if instanceType == "raid" then return "Raid" end
	if instanceType == "party" then return "Dungeon" end
	return "Group"
end

local function counts(session)
	local here, gone = 0, 0
	if not session then return here, gone end
	for _, person in pairs(session.people) do
		if person.present then here = here + 1 else gone = gone + 1 end
	end
	return here, gone
end

local function applyRow(row, person, session)
	if not person then
		row:Hide()
		return
	end
	row:Show()
	local name = person.name or "Unknown"
	if session.instanceType == "raid" and person.subgroup then
		name = person.subgroup .. "  " .. name
	end
	row.name:SetText(name)
	local color = CLASS_COLOR[person.classFile]
	if person.present and color then
		row.name:SetTextColor(color[1], color[2], color[3])
		row.swatch:SetVertexColor(color[1], color[2], color[3], 1)
	elseif person.present then
		row.name:SetTextColor(0.93, 0.90, 0.84)
		row.swatch:SetVertexColor(GOLD[1], GOLD[2], GOLD[3], 1)
	else
		row.name:SetTextColor(0.55, 0.52, 0.46)
		row.swatch:SetVertexColor(0.35, 0.32, 0.26, 1)
	end
	row.className:SetText(person.className or "")
	row.role:SetText(Ironkeep.Group.RoleLabel(person.role))
	local seen = Ironkeep.Group.Seen(person)
	if person.present then
		row.seen:SetText(seen)
		row.seen:SetTextColor(0.82, 0.78, 0.70)
	else
		row.seen:SetText(seen .. "  left")
		row.seen:SetTextColor(0.55, 0.42, 0.36)
	end
end

local function makeRow(parent, index)
	local row = CreateFrame("Frame", nil, parent)
	row:SetSize(460, ROW_H)
	row:SetPoint("TOPLEFT", 0, -((index - 1) * ROW_H))
	local bg = white(row)
	bg:SetAllPoints()
	if index % 2 == 0 then bg:SetVertexColor(1, 1, 1, 0.035) else bg:SetVertexColor(0, 0, 0, 0.12) end
	row.swatch = white(row)
	row.swatch:SetPoint("LEFT", 4, 0)
	row.swatch:SetSize(3, 14)
	row.name = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	row.name:SetPoint("LEFT", 14, 0)
	row.name:SetWidth(180)
	row.name:SetJustifyH("LEFT")
	row.name:SetWordWrap(false)
	if row.name.SetMaxLines then row.name:SetMaxLines(1) end
	row.className = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	row.className:SetPoint("LEFT", 210, 0)
	row.className:SetWidth(80)
	row.className:SetJustifyH("LEFT")
	row.className:SetTextColor(0.75, 0.71, 0.64)
	row.role = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	row.role:SetPoint("LEFT", 300, 0)
	row.role:SetWidth(70)
	row.role:SetJustifyH("LEFT")
	row.role:SetTextColor(0.82, 0.78, 0.70)
	row.seen = row:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	row.seen:SetPoint("LEFT", 380, 0)
	row.seen:SetWidth(74)
	row.seen:SetJustifyH("LEFT")
	row:Hide()
	rows[index] = row
	return row
end

function Ironkeep.Window.Build()
	if window then return end

	StaticPopupDialogs["IRONKEEP_CLEAR"] = {
		text = "Clear this group list? People still in the group start a new one.",
		button1 = "Clear",
		button2 = "Cancel",
		OnAccept = function() Ironkeep.ClearSession() end,
		timeout = 0,
		whileDead = true,
		hideOnEscape = true,
		preferredIndex = 3,
	}

	window = frameWithBackdrop("IronkeepFrame", UIParent)
	window:SetSize(500, 560)
	window:SetFrameStrata("MEDIUM")
	window:SetClampedToScreen(true)
	window:SetMovable(true)
	window:Hide()
	paint(window, INK[1], INK[2], INK[3], INK[4])

	local db = Ironkeep.db or {}
	window:ClearAllPoints()
	window:SetPoint(db.point or "CENTER", UIParent, db.point or "CENTER", db.x or 0, db.y or 40)

	local title = CreateFrame("Frame", nil, window)
	title:SetPoint("TOPLEFT", 0, 0)
	title:SetPoint("TOPRIGHT", 0, 0)
	title:SetHeight(36)
	title:EnableMouse(true)
	title:RegisterForDrag("LeftButton")
	title:SetScript("OnDragStart", function() window:StartMoving() end)
	title:SetScript("OnDragStop", function()
		window:StopMovingOrSizing()
		savePoint()
	end)

	local titleText = title:CreateFontString(nil, "OVERLAY", "GameFontNormalLarge")
	titleText:SetPoint("LEFT", 16, 0)
	titleText:SetText("Ironkeep")
	titleText:SetTextColor(GOLD[1], GOLD[2], GOLD[3])

	local close = CreateFrame("Button", nil, title)
	close:SetPoint("RIGHT", -10, 0)
	close:SetSize(48, 22)
	close:SetNormalFontObject(GameFontHighlightSmall)
	close:SetText("Close")
	close:SetScript("OnClick", function() Ironkeep.Window.Hide() end)

	local rule = white(window)
	rule:SetPoint("TOPLEFT", title, "BOTTOMLEFT", 0, 0)
	rule:SetPoint("TOPRIGHT", title, "BOTTOMRIGHT", 0, 0)
	rule:SetHeight(1)
	rule:SetVertexColor(GOLD[1], GOLD[2], GOLD[3], 0.9)

	window.place = window:CreateFontString(nil, "OVERLAY", "GameFontHighlight")
	window.place:SetPoint("TOPLEFT", 16, -46)
	window.place:SetWidth(468)
	window.place:SetJustifyH("LEFT")
	window.place:SetTextColor(0.93, 0.90, 0.84)

	window.summary = window:CreateFontString(nil, "OVERLAY", "GameFontHighlightSmall")
	window.summary:SetPoint("TOPLEFT", 16, -66)
	window.summary:SetWidth(468)
	window.summary:SetJustifyH("LEFT")
	window.summary:SetTextColor(0.70, 0.66, 0.58)

	local header = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	header:SetPoint("TOPLEFT", 28, -90)
	header:SetText("Name")
	local classHeader = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	classHeader:SetPoint("TOPLEFT", 222, -90)
	classHeader:SetText("Class")
	local roleHeader = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	roleHeader:SetPoint("TOPLEFT", 312, -90)
	roleHeader:SetText("Role")
	local seenHeader = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	seenHeader:SetPoint("TOPLEFT", 392, -90)
	seenHeader:SetText("Seen")

	local scroll = CreateFrame("ScrollFrame", nil, window)
	scroll:SetPoint("TOPLEFT", 12, -108)
	scroll:SetPoint("BOTTOMRIGHT", -12, 168)
	scroll:EnableMouseWheel(true)
	scroll:SetScript("OnMouseWheel", function(self, delta)
		local step = ROW_H * 2
		local nextScroll = self:GetVerticalScroll() - delta * step
		local maxScroll = self:GetVerticalScrollRange()
		if nextScroll < 0 then nextScroll = 0 end
		if nextScroll > maxScroll then nextScroll = maxScroll end
		self:SetVerticalScroll(nextScroll)
	end)

	local child = CreateFrame("Frame", nil, scroll)
	child:SetSize(460, ROW_H)
	scroll:SetScrollChild(child)
	window.list = child

	local refresh = button(window, "Refresh", 90)
	refresh:SetPoint("BOTTOMLEFT", 16, 132)
	refresh:SetScript("OnClick", function() Ironkeep.Refresh() end)

	local previous = button(window, "Previous", 90)
	previous:SetPoint("LEFT", refresh, "RIGHT", 8, 0)
	previous:SetScript("OnClick", function()
		Ironkeep.showingPrevious = not Ironkeep.showingPrevious
		Ironkeep.Window.Update()
	end)

	local clear = button(window, "Clear", 90)
	clear:SetPoint("LEFT", previous, "RIGHT", 8, 0)
	clear:SetScript("OnClick", function()
		if not Ironkeep.db or not Ironkeep.db.session then return end
		if StaticPopup_Show then
			StaticPopup_Show("IRONKEEP_CLEAR")
		else
			Ironkeep.ClearSession()
		end
	end)

	local reportLabel = window:CreateFontString(nil, "OVERLAY", "GameFontDisableSmall")
	reportLabel:SetPoint("BOTTOMLEFT", 16, 112)
	reportLabel:SetText("Report - click it, then copy. It stays on this computer.")

	local reportScroll = CreateFrame("ScrollFrame", nil, window)
	reportScroll:SetPoint("BOTTOMLEFT", 16, 14)
	reportScroll:SetSize(468, 94)
	local reportBorder = frameWithBackdrop(nil, window)
	reportBorder:SetPoint("TOPLEFT", reportScroll, "TOPLEFT", -4, 4)
	reportBorder:SetPoint("BOTTOMRIGHT", reportScroll, "BOTTOMRIGHT", 4, -4)
	reportBorder:SetFrameLevel(window:GetFrameLevel())
	paint(reportBorder, 0.05, 0.045, 0.04, 1)
	reportScroll:SetFrameLevel(reportBorder:GetFrameLevel() + 2)

	reportBox = CreateFrame("EditBox", nil, reportScroll)
	reportBox:SetMultiLine(true)
	reportBox:SetAutoFocus(false)
	reportBox:SetFontObject(GameFontHighlightSmall)
	reportBox:SetWidth(460)
	reportBox:SetMaxLetters(8000)
	reportBox:SetScript("OnEscapePressed", function(self) self:ClearFocus() end)
	reportBox:SetScript("OnEditFocusGained", function(self) self:HighlightText() end)
	reportBox:SetScript("OnEditFocusLost", function() Ironkeep.Window.Update() end)
	reportScroll:SetScrollChild(reportBox)
	window.reportLabel = reportLabel
	window.previous = previous
end

function Ironkeep.Window.IsShown()
	return window and window:IsShown()
end

function Ironkeep.Window.Show()
	Ironkeep.Window.Build()
	window:Show()
	if Ironkeep.db then Ironkeep.db.open = true end
	Ironkeep.Window.Update()
end

function Ironkeep.Window.Hide()
	if not window then return end
	window:Hide()
	if Ironkeep.db then Ironkeep.db.open = false end
end

function Ironkeep.Window.Update()
	if not window then return end
	local db = Ironkeep.db
	local session = db and db.session
	if not session then
		window.place:SetText("No group yet")
		window.summary:SetText("Join a party or a raid. The list fills itself, also while this window is closed.")
	else
		local here, gone = counts(session)
		local place = session.place or "Unknown"
		window.place:SetText(place .. " - " .. kindLabel(session.instanceType))
		local summary = here .. " here"
		if gone > 0 then summary = summary .. " - " .. gone .. " left" end
		if session.started and date then
			summary = summary .. " - started " .. date("%H:%M", session.started)
		end
		if here == 0 then
			summary = summary .. " - kept until you clear it"
		end
		window.summary:SetText(summary)
	end

	local people = Ironkeep.Group.Rows(session)
	local shown = math.min(#people, ROW_CAP)
	local child = window.list
	child:SetHeight(math.max(shown, 1) * ROW_H)
	for i = 1, shown do
		applyRow(rows[i] or makeRow(child, i), people[i], session or {})
	end
	for i = shown + 1, #rows do
		rows[i]:Hide()
	end

	if reportBox.HasFocus and reportBox:HasFocus() then return end
	local text
	if Ironkeep.showingPrevious then
		text = (db and db.lastReport) or "Ironkeep group\n\nNo previous list."
		window.reportLabel:SetText("Previous list - click it, then copy.")
		window.previous:SetText("Current")
	else
		text = Ironkeep.Group.Report(session, time and time() or 0)
		window.reportLabel:SetText("Report - click it, then copy. It stays on this computer.")
		window.previous:SetText("Previous")
	end
	local _, breaks = text:gsub("\n", "\n")
	reportBox:SetHeight(math.max(94, (breaks + 1) * 14))
	if reportBox._last ~= text then
		reportBox:SetText(text)
		reportBox._last = text
	end
end
